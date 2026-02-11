"""Base plugin with shared functionality for asset library plugins.

Provides common utilities for database access, async HTTP operations,
and thumbnail downloading/caching that all plugins can use.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp

from uab.core.database import AssetDatabase
from uab.core.interfaces import AssetLibraryPlugin
from uab.core import config

if TYPE_CHECKING:
    from uab.core.models import StandardAsset

logger = logging.getLogger(__name__)


def _describe_error(e: BaseException) -> str:
    """
    Return a stable, non-empty error description for logs/messages.

    Some exceptions (notably `asyncio.TimeoutError`) stringify to an empty string.
    """
    msg = str(e)
    if msg:
        return f"{type(e).__name__}: {msg}"
    return f"{type(e).__name__}: {e!r}"


def format_exception_chain(e: BaseException, max_depth: int = 4) -> str:
    """
    Format an exception (and its cause/context chain) into a non-empty string.

    This is useful in embedded hosts where some exceptions stringify to "".
    """
    parts: list[str] = []
    cur: BaseException | None = e
    seen: set[int] = set()

    while cur is not None and id(cur) not in seen and len(parts) < max_depth:
        seen.add(id(cur))
        parts.append(_describe_error(cur))
        cur = cur.__cause__ or cur.__context__

    return " <- ".join(parts)


class SharedAssetLibraryUtils(AssetLibraryPlugin):
    """
    Base class providing shared functionality for asset library plugins.

    Subclasses should set plugin_id, display_name, and description as class
    attributes, then implement the abstract methods from AssetLibraryPlugin.

    Provides:
        - Database instance (shared or injected)
        - Async HTTP client session management
        - Thumbnail download and caching
        - Common error handling patterns
    """

    # Subclasses must override these
    plugin_id: str = ""
    display_name: str = ""
    description: str = ""

    def __init__(
        self,
        db: AssetDatabase | None = None,
        library_root: Path | None = None,
    ) -> None:
        """
        Initialize the base plugin.

        Args:
            db: Optional database instance (creates default if not provided)
            library_root: Root directory for downloaded assets
        """
        self._db = db or AssetDatabase()
        self._library_root = library_root or config.get_library_dir()
        self._library_root.mkdir(parents=True, exist_ok=True)

        # Plugin-specific thumbnail cache directory
        self._thumbnail_cache_dir = config.get_thumbnail_cache_dir(
            self.plugin_id)
        self._thumbnail_cache_dir.mkdir(parents=True, exist_ok=True)

        # Lazy-initialized HTTP session (tied to an event loop)
        self._session: aiohttp.ClientSession | None = None
        self._session_loop: asyncio.AbstractEventLoop | None = None

        # Some embedded hosts (notably Houdini) may raise NotImplementedError from
        # the event loop networking primitives that aiohttp relies on. When this
        # is detected, permanently fall back to urllib for the lifetime of this
        # plugin instance to avoid noisy retries/log spam.
        self._http_force_urllib: bool = False
        self._http_force_urllib_logged: bool = False
        self._http_force_urllib_reason: str | None = None

    @property
    def db(self) -> AssetDatabase:
        """Access the database instance."""
        return self._db

    @property
    def library_root(self) -> Path:
        """Root directory for this plugin's downloaded assets."""
        return self._library_root / self.plugin_id

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Get or create the aiohttp session.

        The session is created lazily and reused for all HTTP requests
        within the same event loop. If the event loop has changed (e.g.,
        when running without qasync), a new session is created.
        """
        current_loop = asyncio.get_running_loop()

        # Check if we need a new session:
        # - No session exists
        # - Session is closed
        # - Session was created in a different event loop
        needs_new_session = (
            self._session is None
            or self._session.closed
            or self._session_loop is not current_loop
        )

        if needs_new_session:
            # Close old session if it exists and is from a different loop
            if self._session is not None and not self._session.closed:
                try:
                    await self._session.close()
                except Exception:
                    pass  # Ignore errors closing old session

            timeout = aiohttp.ClientTimeout(total=30, connect=10)

            # Configure SSL context - try certifi first, then system, then disable
            ssl_context = self._create_ssl_context()
            connector = aiohttp.TCPConnector(ssl=ssl_context)

            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": "UAB/1.0"},
                trust_env=True,
            )
            self._session_loop = current_loop

        return self._session

    def _create_ssl_context(self):
        """
        Create an SSL context for HTTPS requests.

        Tries in order:
        1. certifi CA bundle (most reliable in embedded environments)
        2. System default SSL context
        3. Disabled verification (fallback, logs warning)
        """
        import ssl

        try:
            import certifi
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            logger.debug("Using certifi CA bundle for SSL")
            return ssl_context
        except ImportError:
            logger.debug("certifi not available, trying system SSL")

        try:
            ssl_context = ssl.create_default_context()
            return ssl_context
        except Exception as e:
            logger.warning(f"System SSL context failed: {e}")

        logger.warning(
            "SSL certificate verification disabled - install certifi for proper SSL: "
            "pip install certifi"
        )
        return False

    async def close(self) -> None:
        """Close the HTTP session. Call when done with the plugin."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._session_loop = None

    async def _fetch_json(
        self,
        url: str,
        retries: int = 3,
        backoff_factor: float = 0.5,
    ) -> dict | list:
        """
        Fetch JSON from a URL with retry logic.

        Args:
            url: The URL to fetch
            retries: Number of retry attempts
            backoff_factor: Multiplier for exponential backoff

        Returns:
            Parsed JSON response

        Raises:
            aiohttp.ClientError: If all retries fail
        """
        if self._http_force_urllib:
            try:
                return await asyncio.to_thread(self._fetch_json_sync, url)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    f"Failed to fetch {url} via urllib: {format_exception_chain(e)}"
                )
                raise aiohttp.ClientError(
                    f"Failed to fetch {url}: {format_exception_chain(e)}"
                ) from e

        session = await self._get_session()
        last_error: Exception | None = None

        for attempt in range(retries):
            try:
                async with session.get(url) as response:
                    response.raise_for_status()
                    return await response.json()
            except asyncio.CancelledError:
                raise
            except NotImplementedError as e:
                last_error = e
                self._http_force_urllib = True
                self._http_force_urllib_reason = type(e).__name__
                if not self._http_force_urllib_logged:
                    logger.info(
                        "aiohttp HTTP backend unavailable (%s); using urllib for HTTP requests.",
                        self._http_force_urllib_reason,
                    )
                    self._http_force_urllib_logged = True
                break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt < retries - 1:
                    wait_time = backoff_factor * (2**attempt)
                    logger.warning(
                        f"Request to {url} failed (attempt {attempt + 1}/{retries}), "
                        f"retrying in {wait_time}s: {_describe_error(e)}"
                    )
                    await asyncio.sleep(wait_time)

        base_err: Exception = last_error or aiohttp.ClientError(f"Failed to fetch {url}")

        # Fall back to stdlib urllib in a worker thread.
        try:
            value = await asyncio.to_thread(self._fetch_json_sync, url)
            if not isinstance(base_err, NotImplementedError):
                logger.debug(
                    "Fetched %s via urllib fallback after aiohttp failure: %s",
                    url,
                    format_exception_chain(base_err),
                )
            return value
        except asyncio.CancelledError:
            raise
        except Exception as fallback_err:
            logger.error(
                "Failed to fetch %s via aiohttp (%s) and urllib (%s)",
                url,
                format_exception_chain(base_err),
                format_exception_chain(fallback_err),
            )
            raise aiohttp.ClientError(
                f"Failed to fetch {url}: {format_exception_chain(base_err)} "
                f"(urllib fallback also failed: {format_exception_chain(fallback_err)})"
            ) from fallback_err

    async def _download_file(
        self,
        url: str,
        dest_path: Path,
        retries: int = 3,
        backoff_factor: float = 0.5,
        progress_callback: callable | None = None,
    ) -> Path:
        """
        Download a file from URL to local path with retry logic.

        This is necessary becasue some embedded hosts (HOUDINI, LOOKING AT YOU) have aiohttp/SSL/proxy quirks.

        Args:
            url: The URL to download from
            dest_path: Local destination path
            retries: Number of retry attempts
            backoff_factor: Multiplier for exponential backoff
            progress_callback: Optional callback(bytes_downloaded, total_bytes)

        Returns:
            The destination path

        Raises:
            aiohttp.ClientError: If all retries fail
        """
        # Ensure parent directory exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if self._http_force_urllib:
            try:
                return await asyncio.to_thread(
                    self._download_file_sync, url, dest_path, progress_callback
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "Failed to download %s via urllib: %s",
                    url,
                    format_exception_chain(e),
                )
                raise aiohttp.ClientError(
                    f"Failed to download {url}: {format_exception_chain(e)}"
                ) from e

        session = await self._get_session()
        last_error: Exception | None = None

        for attempt in range(retries):
            try:
                async with session.get(url) as response:
                    response.raise_for_status()
                    total_size = response.content_length or 0
                    downloaded = 0

                    temp_path = dest_path.with_suffix(
                        dest_path.suffix + ".tmp")
                    try:
                        with open(temp_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                                downloaded += len(chunk)
                                if progress_callback:
                                    progress_callback(downloaded, total_size)

                        temp_path.rename(dest_path)
                        return dest_path

                    except Exception:
                        if temp_path.exists():
                            temp_path.unlink()
                        raise

            except asyncio.CancelledError:
                raise
            except NotImplementedError as e:
                last_error = e
                self._http_force_urllib = True
                self._http_force_urllib_reason = type(e).__name__
                if not self._http_force_urllib_logged:
                    logger.info(
                        "aiohttp HTTP backend unavailable (%s); using urllib for HTTP requests.",
                        self._http_force_urllib_reason,
                    )
                    self._http_force_urllib_logged = True
                break
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                last_error = e
                if attempt < retries - 1:
                    wait_time = backoff_factor * (2**attempt)
                    logger.warning(
                        f"Download from {url} failed (attempt {attempt + 1}/{retries}), "
                        f"retrying in {wait_time}s: {_describe_error(e)}"
                    )
                    await asyncio.sleep(wait_time)

        base_err: Exception = last_error or aiohttp.ClientError(f"Failed to download {url}")

        # Last resort: stdlib urllib download in a worker thread.
        try:
            path = await asyncio.to_thread(
                self._download_file_sync, url, dest_path, progress_callback
            )
            if not isinstance(base_err, NotImplementedError):
                logger.debug(
                    "Downloaded %s via urllib fallback after aiohttp failure: %s",
                    url,
                    format_exception_chain(base_err),
                )
            return path
        except asyncio.CancelledError:
            raise
        except Exception as fallback_err:
            logger.error(
                "Failed to download %s via aiohttp (%s) and urllib (%s)",
                url,
                format_exception_chain(base_err),
                format_exception_chain(fallback_err),
            )
            raise aiohttp.ClientError(
                f"Failed to download {url}: {format_exception_chain(base_err)} "
                f"(urllib fallback also failed: {format_exception_chain(fallback_err)})"
            ) from fallback_err

    def _urllib_ssl_context(self):
        """Best-effort SSL context for stdlib urllib HTTPS."""
        import ssl

        try:
            import certifi

            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass

        try:
            return ssl.create_default_context()
        except Exception:
            # Worst case: disable verification (still encrypted).
            return ssl._create_unverified_context()

    def _fetch_json_sync(self, url: str) -> dict | list:
        """Synchronous JSON fetch (urllib). Intended for thread offload."""
        import json
        import urllib.request

        ctx = self._urllib_ssl_context()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "UAB/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = resp.read()
        value = json.loads(data)
        if not isinstance(value, (dict, list)):
            raise TypeError(f"Unexpected JSON type from {url}: {type(value)}")
        return value

    def _download_file_sync(
        self,
        url: str,
        dest_path: Path,
        progress_callback: callable | None = None,
    ) -> Path:
        """Synchronous file download (urllib). Intended for thread offload."""
        import urllib.request

        ctx = self._urllib_ssl_context()
        req = urllib.request.Request(url, headers={"User-Agent": "UAB/1.0"})

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

        downloaded = 0
        total_size = 0

        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                # `length` is not guaranteed; fall back to header.
                length_any = getattr(resp, "length", None)
                if isinstance(length_any, int):
                    total_size = length_any
                else:
                    header = resp.headers.get("Content-Length")
                    if header and header.isdigit():
                        total_size = int(header)

                with open(temp_path, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)

            temp_path.rename(dest_path)
            return dest_path
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise

    async def download_thumbnail(
        self,
        asset: Any,
        url: str | None = None,
    ) -> Path | None:
        """
        Download and cache an asset's thumbnail.

        Args:
            asset: The asset to download thumbnail for
            url: Optional URL override (uses asset.thumbnail_url if not provided)

        Returns:
            Path to cached thumbnail, or None if download failed
        """
        thumbnail_url = url or asset.thumbnail_url
        if not thumbnail_url:
            return None

        url_path = thumbnail_url.split("?")[0]  # Remove query params
        ext = Path(url_path).suffix.lower() or ".jpg"

        cache_filename = f"{asset.source}_{asset.external_id}{ext}"
        cache_path = self._thumbnail_cache_dir / cache_filename

        if cache_path.exists():
            return cache_path

        try:
            await self._download_file(thumbnail_url, cache_path)
            logger.debug(
                f"Downloaded thumbnail for {asset.name} to {cache_path}")
            return cache_path
        except Exception as e:
            logger.warning(
                f"Failed to download thumbnail for {asset.name}: {e}")
            return None

    def get_thumbnail_cache_path(self, asset: Any) -> Path | None:
        """
        Get the cached thumbnail path for an asset if it exists.

        Args:
            asset: The asset to get thumbnail for

        Returns:
            Path to cached thumbnail if exists, None otherwise
        """
        ext = ".jpg"  # Default fallback
        if asset.thumbnail_url:
            url_path = asset.thumbnail_url.split("?")[0]
            url_ext = Path(url_path).suffix.lower()
            if url_ext:
                ext = url_ext

        cache_filename = f"{asset.source}_{asset.external_id}{ext}"
        cache_path = self._thumbnail_cache_dir / cache_filename
        return cache_path if cache_path.exists() else None
