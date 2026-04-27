import time
import random
from datetime import datetime, timezone

import orjson
import undetected_chromedriver as uc
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .. import utils
from ..models.configs import SeleniumConfig
from ..models.data import ResponseOutput
from ..models.searches import SearchParams


TRANSLATIONS = {
    "en": {
        "reject_all": "Reject all",
        "show_all": "Show all",
        "not_now": "Not now",
        "view_related": "View related links"
    },
    "de": {
        "reject_all": "Alle ablehnen",
        "show_all": "Alle anzeigen",
        "not_now": "Jetzt nicht",
        "view_related": "Zugehörige Links ansehen"
    },
    "es": {
        "reject_all": "Rechazar todo",
        "show_all": "Mostrar todo",
        "not_now": "Ahora no",
        "view_related": "Ver enlaces relacionados"
    },
    "pt": {
        "reject_all": "Rejeitar tudo",
        "show_all": "Mostrar tudo",
        "not_now": "Agora não",
        "view_related": "Ver links relacionados"
    }
}


class SeleniumDriver:
    """Handle Selenium-based web interactions for search engines"""

    def __init__(self, config: SeleniumConfig, logger):
        """Initialize a Selenium driver with the given configuration

        Args:
            config (SeleniumConfig): Configuration for Selenium
            logger: Logger instance
        """
        self.config = config
        self.log = logger
        self.driver = None
        self.browser_info = {}

    def init_driver(self) -> None:
        """Initialize Chrome driver with selenium-specific config"""
        self.log.debug(f"SERP | init uc chromedriver | kwargs: {self.config.__dict__}")
        self.driver = uc.Chrome(**self.config.__dict__)

        # Log version information
        self.browser_info = {
            "browser_id": "",
            "browser_name": self.driver.capabilities["browserName"],
            "browser_version": self.driver.capabilities["browserVersion"],
            "driver_version": self.driver.capabilities["chrome"]["chromedriverVersion"].split(" ")[
                0
            ],
            "user_agent": self.driver.execute_script("return navigator.userAgent"),
        }
        self.browser_info["browser_id"] = utils.hash_id(
            orjson.dumps(self.browser_info).decode("utf-8")
        )
        self.log.debug(orjson.dumps(self.browser_info, option=orjson.OPT_INDENT_2))

    def send_typed_query(self, query: str):
        """Send a typed query to the search box"""
        time.sleep(2)
        self.driver.get("https://www.google.com")
        time.sleep(2)
        search_box = self.driver.find_element(By.ID, "APjFqb")
        search_box.clear()
        search_box.send_keys(query)
        search_box.send_keys(Keys.RETURN)

    def send_request(self, search_params: SearchParams) -> ResponseOutput:
        """Visit a URL with selenium and save HTML response"""

        response_output = ResponseOutput(
            url=search_params.url,
            user_agent=self.browser_info.get("user_agent", ""),
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        )

        try:
            self.driver.get(search_params.url)
            time.sleep(2)
            if search_params.ai_mode:
                # Double check if still necessary
                # WebDriverWait(self.driver, 10).until(
                #     EC.visibility_of_element_located(
                #         (By.CSS_SELECTOR, 'button[aria-label="Positive feedback"]')
                #     )
                # )
                pass
            else:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "search"))
                )
            time.sleep(2)
            response_output.html = self.driver.page_source
            response_output.url = self.driver.current_url
            response_output.response_code = 200

            # Expand AI overview if requested
            if search_params.ai_expand:
                expanded_html = self.expand_ai_overview(search_params)
                if expanded_html:
                    len_diff = len(expanded_html) - len(response_output.html)
                    self.log.debug(f"SERP | expanded html | len diff: {len_diff}")
                    response_output.html = expanded_html
                    citation_data = self.collect_citations(search_params)
                response_output.citations = citation_data

        except Exception as e:
            self.log.exception(f"SERP | Chromedriver error | {str(e)}")
        finally:
            self.delete_cookies()

        return response_output

    def expand_ai_overview(self, search_params):
        """Expand AI overview box by clicking it
        Somewhat gratuitous expansion to this function,
        compatible with AI Mode windows. Possibly deprecated."""
        # show_more_button_xpath = "//div[@jsname='rPRdsc' and @role='button']"
        # show_all_button_xpath = '//div[contains(@class, "trEk7e") and @role="button"]'

        XPATHS = {
            "reject_all": "//button[.//div[text()='Alle ablehnen']]",
            "show_more_aioverivew": "//div[@jsname='rPRdsc' and @role='button']",
            # "show_all_aimode": '//div[@role="button" and .//span[text()="Show all"]]',
            "show_all_aimode": '//div[@role="button" and .//span[text()="Mostrar todo"]]',
            "show_all_aioverview": '//div[@role="button" and .//span[text()="Alle anzeigen"]]',
            "not_now": '//g-raised-button[@role="button" and .//div[normalize-space(.)="Not now"]]',
        }

        debug = True

        def dbg(*args):
            if debug:
                print("[expand_ai_overview]", *args)

        def try_click(xpath, timeout=1):
            dbg(f"Attempting click: {xpath}")
            try:
                el = WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                el.click()
                dbg(f"Click succeeded: {xpath}")
                return True
            except Exception as e:
                dbg(f"Click failed: {xpath} — {type(e).__name__}: {e}")
                return False

        dbg(f"ai_mode={search_params.ai_mode}")

        dbg("Checking for reject_all button...")
        rejected = try_click(XPATHS["reject_all"])
        dbg(f"reject_all result: {'clicked' if rejected else 'not found/skipped'}")

        if search_params.ai_mode:
            dbg("Branch: AI mode")

            dbg("Checking for show_all button...")
            showed = try_click(XPATHS["show_all_aimode"])
            dbg(f"show_all result: {'clicked' if showed else 'not found/skipped'}")

            dbg("Grabbing page source...")
            source = self.driver.page_source
            dbg(f"Page source length: {len(source)} chars")
            return source

        # Standard (non-AI mode) expansion
        dbg("Branch: standard mode")
        expanded_source = None

        dbg("Checking for not_now button...")
        if try_click(XPATHS["not_now"]):
            dbg("not_now clicked, sleeping 2s...")
            time.sleep(2)
            expanded_source = self.driver.page_source
            dbg(f"Page source grabbed after not_now: {len(expanded_source)} chars")

        dbg("Checking for show_more button...")
        if try_click(XPATHS["show_more_aioverivew"]):
            dbg("show_more clicked, sleeping 2s...")
            time.sleep(2)
            dbg("Checking for show_all after show_more...")
            try_click(XPATHS["show_all_aioverview"])
            expanded_source = self.driver.page_source
            dbg(f"Page source grabbed after show_more: {len(expanded_source)} chars")

        dbg(f"Returning source: {'None' if expanded_source is None else f'{len(expanded_source)} chars'}")
        return expanded_source

    def collect_citations(self, search_params, max_wait_time=2):
        """Collect citation URLs by clicking each source button and scraping visible links."""
        debug = True

        def dbg(*args):
            if debug:
                print("[collect_citations]", *args)

        content_data = {}
        processed_buttons = set()

        BUTTON_CONFIGS = {
            "ai_mode": [
                {
                    "xpath": '//button[@aria-label="View related links"]',
                    "key_attr": "data-icl-uuid",
                    "key_via_parent": False,
                    "link_class": "NDNGvf",
                },
                {
                    "xpath": "//button[contains(@class, 'rBl3me') and @data-amic='true' and @data-icl-uuid]",
                    "key_attr": "data-icl-uuid",
                    "key_via_parent": False,
                    "link_class": "NDNGvf",
                },
            ],
            "standard": [
                {
                    "xpath": "//div[@role='button' and @jsname='HtgYJd'] | //span[@role='button' and @jsname='HtgYJd']",
                    "key_attr": "data-cid",
                    "key_via_parent": True,
                    "link_class": "KEVENd",
                },
                {
                    # "xpath": "//button[@class='rBl3me' and @jsname='sIoYce']",
                    "xpath": "//button[contains(@class, 'rBl3me')]",                    
                    "key_attr": "data-icl-uuid",
                    "key_via_parent": False,
                    "link_class": "NDNGvf",
                },
            ],
        }

        CLOSE_BUTTON_XPATH = '//button[contains(@class, "hXknlc")]'

        def try_close_dialog():
            try:
                close_btn = WebDriverWait(self.driver, 1).until(
                    EC.element_to_be_clickable((By.XPATH, CLOSE_BUTTON_XPATH))
                )
                close_btn.click()
                dbg("Dialog closed successfully.")
                return True
            except Exception as e:
                dbg(f"No dialog to close or close failed: {type(e).__name__}: {e}")
                return False

        mode = "ai_mode" if search_params.ai_mode else "standard"
        configs = BUTTON_CONFIGS[mode]
        dbg(f"Mode: {mode}, max_wait_time={max_wait_time}")

        # Resolve which config/buttons to use
        target_buttons, link_class, active_config = [], None, None
        for config in configs:
            dbg(f"Trying xpath: {config['xpath']}")
            all_buttons = self.driver.find_elements(By.XPATH, config["xpath"])
            dbg(f"Total buttons found: {len(all_buttons)}")
            visible = [b for b in all_buttons if b.is_displayed()]
            dbg(f"Visible buttons: {len(visible)}")
            if visible:
                target_buttons = visible
                link_class = config["link_class"]
                active_config = config
                dbg(f"Using config: key_attr={config['key_attr']}, key_via_parent={config['key_via_parent']}, link_class={link_class}")
                break
            else:
                dbg("No visible buttons for this config, trying next...")

        if not target_buttons:
            dbg("No visible buttons found across all configs. Returning empty.")
            return content_data

        dbg(f"Processing {len(target_buttons)} buttons...")

        for i, button in enumerate(target_buttons):
            dbg(f"--- Button {i + 1}/{len(target_buttons)} ---")
            try:
                # Extract key
                if active_config["key_via_parent"]:
                    parent = button.find_element(By.XPATH, "./..")
                    key = parent.get_attribute(active_config["key_attr"])
                    dbg(f"Key from parent attribute '{active_config['key_attr']}': {key}")
                else:
                    key = button.get_attribute(active_config["key_attr"])
                    dbg(f"Key from button attribute '{active_config['key_attr']}': {key}")

                if not key:
                    dbg("No key found, skipping button.")
                    continue
                if key in processed_buttons:
                    dbg(f"Key '{key}' already processed, skipping.")
                    continue

                # Scroll into view
                dbg(f"Scrolling to button with key: {key}")
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button
                )
                time.sleep(0.2)

                # Click
                try:
                    WebDriverWait(self.driver, max_wait_time).until(EC.element_to_be_clickable(button))
                    button.click()
                    dbg("Clicked button normally.")
                except ElementClickInterceptedException:
                    dbg("Normal click intercepted, falling back to JS click.")
                    self.driver.execute_script("arguments[0].click();", button)

                dbg("Sleeping 0.5s for dynamic content...")
                time.sleep(0.5)

                # Scrape visible links
                dbg(f"Waiting for links with class '{link_class}'...")
                try:
                    WebDriverWait(self.driver, max_wait_time).until(
                        lambda d: d.find_elements(By.CLASS_NAME, link_class)
                    )
                    all_links = self.driver.find_elements(By.CLASS_NAME, link_class)
                    dbg(f"Total '{link_class}' links found: {len(all_links)}")
                    visible_links = [l for l in all_links if l.is_displayed()]
                    dbg(f"Visible '{link_class}' links: {len(visible_links)}")

                    urls = [l.get_attribute("href") for l in visible_links if l.get_attribute("href")]
                    content_data[key] = urls
                    dbg(f"Extracted {len(urls)} URLs for key '{key}':")
                    for j, url in enumerate(urls, 1):
                        dbg(f"  {j}. {url[:80]}{'...' if len(url) > 80 else ''}")

                except Exception as e:
                    dbg(f"Failed to find '{link_class}' links: {type(e).__name__}: {e}")
                    content_data[key] = []

                # Close dialog before moving to next button
                dbg("Attempting to close citation dialog...")
                try_close_dialog()
                time.sleep(0.2)

                processed_buttons.add(key)

                pause = random.uniform(0.05, 0.15)
                dbg(f"Pausing {pause:.2f}s before next button...")
                time.sleep(pause)

            except Exception as e:
                dbg(f"Unhandled error on button {i + 1}: {type(e).__name__}: {e}")
                try_close_dialog()  # Attempt cleanup even on error

        dbg(f"Done. Collected citations for {len(content_data)} keys:")
        for key, urls in content_data.items():
            dbg(f"  {key}: {len(urls)} URLs")
            for j, url in enumerate(urls, 1):
                dbg(f"    {j}. {url[:80]}{'...' if len(url) > 80 else ''}")

        return content_data

    def cleanup(self) -> bool:
        """Clean up resources, particularly Selenium's browser instance

        Returns:
            bool: True if cleanup was successful or not needed, False if cleanup failed
        """
        if self.driver:
            try:
                self.delete_cookies()
                self.close_all_windows()
                self.driver.quit()
                self.driver = None
                self.log.debug("Browser successfully closed")
                return True
            except Exception as e:
                self.log.warning(f"Failed to close browser: {e}")
                self.driver = None
                return False
        return True

    def close_all_windows(self):
        try:
            # Close all tabs/windows
            original_handle = self.driver.current_window_handle
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                self.driver.close()
            self.driver.switch_to.window(original_handle)
            self.driver.close()
        except Exception:
            pass

    def delete_cookies(self):
        """Delete all cookies from the browser"""
        if self.driver:
            try:
                self.driver.delete_all_cookies()
            except Exception as e:
                self.log.warning(f"Failed to delete cookies: {str(e)}")

    def __del__(self):
        """Destructor to ensure browser is closed when object is garbage collected"""
        try:
            self.cleanup()
        except Exception:
            pass
