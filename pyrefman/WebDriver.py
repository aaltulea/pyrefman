import time
from pathlib import Path
from typing import Callable, Literal, Optional, List

from playwright.sync_api import (
    sync_playwright,
    Browser,
    BrowserContext,
    Page,
    Locator,
    TimeoutError as PWTimeoutError,
)

from pyrefman.SingletonClass import Singleton
from pyrefman.Utils import get_downloads_dir


# Minimal Selenium-like By constants (so callers can keep using By.ID etc.)
class By:
    ID = "id"
    XPATH = "xpath"
    CSS_SELECTOR = "css selector"
    TAG_NAME = "tag name"


BrowserName = Literal["chromium", "firefox", "webkit"]


class OperationAbortedError(RuntimeError):
    pass


class RelaunchHeadedBrowserError(RuntimeError):
    pass


def expect_download_save_as(
        page: Page,
        click_fn: Callable[[], None],
        target_path: Path,
        timeout_s: int = 30,
) -> Path:
    """
    Wrap a click/action that triggers a browser download, wait for Playwright's download event,
    and save to an explicit target path.

    This avoids polling the OS downloads folder and works reliably across browsers.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    timeout_ms = int(timeout_s * 1000)

    with page.expect_download(timeout=timeout_ms) as dl_info:
        click_fn()

    download = dl_info.value
    download.save_as(str(target_path))
    return target_path


class WebDriver(metaclass=Singleton):
    """
    Playwright wrapper that exposes Selenium-like APIs:
      - find_element(By.ID / By.CSS_SELECTOR, selector)
      - find_elements(By.XPATH / By.TAG_NAME, selector)
    """

    def __init__(self, browser_name: BrowserName = "chromium", headless: bool = False):
        self.browser_name = browser_name
        self.headless = False

        self._pw = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # -------------------------
    # Lifecycle
    # -------------------------
    def get_page(self) -> Page:
        if self._page is None:
            self._start()
        return self._page

    def prepare_run(self) -> None:
        self.headless = False
        self.quit_driver()

    def request_abort(self) -> None:
        self.quit_driver()

    def is_abort_requested(self) -> bool:
        return False

    def ensure_not_aborted(self) -> None:
        return None

    def raise_if_aborted(self, exc: Exception) -> None:
        return None

    def get_download_timeout(self, default_timeout_s: int) -> int:
        return default_timeout_s

    def mark_download_detected(self) -> None:
        return None

    def should_fallback_to_headed(self) -> bool:
        return False

    def switch_to_headed_mode(self, reason: str | None = None) -> None:
        return None

    def _start(self) -> None:
        downloads_path = Path(get_downloads_dir())
        downloads_path.mkdir(parents=True, exist_ok=True)

        self._pw = sync_playwright().start()
        browser_launcher = getattr(self._pw, self.browser_name)
        self._browser = browser_launcher.launch(headless=False)

        self._context = self._browser.new_context(
            accept_downloads=True,
        )
        self._page = self._context.new_page()
        self._apply_preferred_window_size()

    def _apply_preferred_window_size(self) -> None:
        if self.browser_name != "chromium" or self._context is None or self._page is None:
            return

        try:
            screen_size = self._page.evaluate(
                """() => ({
                    width: window.screen.availWidth || window.screen.width || 0,
                    height: window.screen.availHeight || window.screen.height || 0
                })"""
            )
            available_width = int(screen_size.get("width") or 0)
            available_height = int(screen_size.get("height") or 0)
            if available_width <= 0 or available_height <= 0:
                return

            width = max(900, int(available_width * 0.9))
            height = max(700, int(available_height * 0.9))

            session = self._context.new_cdp_session(self._page)
            window_info = session.send("Browser.getWindowForTarget")
            session.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window_info["windowId"],
                    "bounds": {
                        "width": width,
                        "height": height,
                    },
                },
            )
        except Exception:
            pass

    def quit_driver(self) -> None:
        try:
            if self._page:
                self._page.close()
        except Exception:
            pass
        finally:
            self._page = None

        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        finally:
            self._context = None

        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        finally:
            self._browser = None

        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        finally:
            self._pw = None

    def set_browser(self, browser_name: BrowserName) -> None:
        if browser_name == self.browser_name:
            return
        self.browser_name = browser_name
        if self._page is not None:
            self.quit_driver()
            self._start()

    # -------------------------
    # Navigation
    # -------------------------
    def navigate_to(self, url: str, retries: int = 3, retry_sleep: float = 5.0) -> None:
        page = self.get_page()
        page.goto(url, wait_until="domcontentloaded")

    def navigate_to2(self, url: str, retries: int = 3, retry_sleep: float = 5.0) -> None:
        last_exc = None
        for _ in range(retries):
            try:
                page = self.get_page()
                page.goto(url, wait_until="domcontentloaded")
                return
            except Exception as e:
                last_exc = e
                try:
                    self.quit_driver()
                except Exception:
                    pass
                time.sleep(retry_sleep)
        raise last_exc

    # -------------------------
    # Selenium-ish selector translation
    # -------------------------
    def _to_locator(self, by: str, value: str) -> Locator:
        """
        Convert (By, value) into a Playwright Locator.
        """
        page = self.get_page()
        by_norm = (by or "").lower().strip()

        if by_norm in (By.CSS_SELECTOR, "css", "cssselector", "css selector"):
            return page.locator(value)

        if by_norm in (By.ID, "id"):
            # CSS.escape isn't directly available here; Playwright handles most IDs fine with #id.
            # If you have IDs with special chars, we can add a safe escaper.
            return page.locator(f"#{value}")

        if by_norm in (By.XPATH, "xpath"):
            return page.locator(f"xpath={value}")

        if by_norm in (By.TAG_NAME, "tag_name", "tag name"):
            # Expect value like "div", "a", "span"
            return page.locator(value)

        raise ValueError(f"Unsupported locator strategy: {by}")

    # -------------------------
    # Selenium-like APIs requested
    # -------------------------
    def find_element(
            self,
            by: str,
            value: str,
            timeout: int = 60 * 3,  # seconds
            state: Literal["attached", "visible"] = "attached",
            scroll_once: bool = True,
    ) -> Locator:
        """
        Selenium-like find_element. Waits until the element is present (or visible if requested).
        Returns a Playwright Locator.
        """
        loc = self._to_locator(by, value)
        page = self.get_page()

        did_scroll = False
        timeout_ms = int(timeout * 1000)

        try:
            loc.first.wait_for(state=state, timeout=timeout_ms)
            return loc.first
        except PWTimeoutError as e:
            if scroll_once and not did_scroll:
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    page.evaluate("window.scrollTo(0, 0);")
                    did_scroll = True
                    loc.first.wait_for(state=state, timeout=timeout_ms)
                    return loc.first
                except Exception:
                    pass
            raise TimeoutError(f"wait_for timed out after {timeout}s for {by}='{value}': {e}")
    def find_elements(
            self,
            by: str,
            value: str,
            timeout: int = 30,  # seconds (for "at least one" behavior)
            min_count: int = 0,
            state: Literal["attached", "visible"] = "attached",
    ) -> List[Locator]:
        """
        Selenium-like find_elements.
        - If min_count == 0 (default): returns immediately with whatever exists (can be empty).
        - If min_count > 0: waits up to timeout for at least min_count elements.
        Returns a list of Locators (each one points to a specific nth element).
        """
        loc = self._to_locator(by, value)
        timeout_ms = int(timeout * 1000)

        if min_count > 0:
            # wait until there are at least min_count matches
            try:
                loc.nth(min_count - 1).wait_for(state=state, timeout=timeout_ms)
            except PWTimeoutError as e:
                raise TimeoutError(
                    f"wait_for timed out after {timeout}s waiting for >= {min_count} elements for {by}='{value}': {e}"
                )

        count = loc.count()
        return [loc.nth(i) for i in range(count)]

    # -------------------------
    # Convenience wrappers to match exactly what you listed
    # -------------------------
    def find_element_css(self, css_selector: str, **kwargs) -> Locator:
        return self.find_element(By.CSS_SELECTOR, css_selector, **kwargs)

    def find_element_id(self, element_id: str, **kwargs) -> Locator:
        return self.find_element(By.ID, element_id, **kwargs)

    def find_elements_xpath(self, xpath: str, **kwargs) -> List[Locator]:
        return self.find_elements(By.XPATH, xpath, **kwargs)

    def find_elements_tag_name(self, tag_name: str, **kwargs) -> List[Locator]:
        return self.find_elements(By.TAG_NAME, tag_name, **kwargs)
