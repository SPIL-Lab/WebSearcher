import time
from datetime import datetime, timezone

import orjson
import undetected_chromedriver as uc
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .. import utils
from ..models.configs import SeleniumConfig
from ..models.data import ResponseOutput
from ..models.searches import SearchParams


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
                WebDriverWait(self.driver, 10).until(
                    EC.visibility_of_element_located(
                        (By.CSS_SELECTOR, 'button[aria-label="Positive feedback"]')
                    )
                )
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
                expanded_html = self.expand_ai_overview()
                if expanded_html:
                    len_diff = len(expanded_html) - len(response_output.html)
                    self.log.debug(f"SERP | expanded html | len diff: {len_diff}")
                    response_output.html = expanded_html
                    citation_data = self.collect_citations()
                response_output.citations = citation_data

        except Exception as e:
            self.log.exception(f"SERP | Chromedriver error | {str(e)}")
        finally:
            self.delete_cookies()

        return response_output

    def expand_ai_overview(self):
        """Expand AI overview box by clicking it
        Somewhat gratuitous expansion to this function,
        compatible with AI Mode windows. Possibly deprecated."""
        # show_more_button_xpath = "//div[@jsname='rPRdsc' and @role='button']"
        # show_all_button_xpath = '//div[contains(@class, "trEk7e") and @role="button"]'

        XPATHS = {
            "show_more": "//div[@jsname='rPRdsc' and @role='button']",
            "show_all": '//div[@role="button" and .//span[text()="Show all"]]',
            "not_now": '//g-raised-button[@role="button" and .//div[normalize-space(.)="Not now"]]',
        }

        def try_click(xpath, timeout=1):
            try:
                el = WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                el.click()
                return True
            except (TimeoutException, Exception):
                return False

        # AI Mode Expansion
        if search_params.ai_mode:
            try_click(XPATHS["show_all"])
            return self.driver.page_source

        # AI Overview expansion
        expanded_source = None

        if try_click(XPATHS["not_now"]):
            time.sleep(2)
            expanded_source = self.driver.page_source

        if try_click(XPATHS["show_more"]):
            time.sleep(2)
            try_click(XPATHS["show_all"])
            expanded_source = self.driver.page_source

        return expanded_source

    def collect_citations(self, max_wait_time=2):
        """Collect citation URLs by clicking each source button and scraping visible links."""
        content_data = {}
        processed_buttons = set()

        # Config per mode: (xpath, key_attr, key_via_parent, link_class)
        BUTTON_CONFIGS = {
            "ai_mode": [
                {
                    "xpath": '//button[@aria-label="View related links"]',
                    "key_attr": "data-icl-uuid",
                    "key_via_parent": False,
                    "link_class": "NDNGvf",
                }
            ],
            "standard": [
                {
                    "xpath": "//div[@role='button' and @jsname='HtgYJd'] | //span[@role='button' and @jsname='HtgYJd']",
                    "key_attr": "data-cid",
                    "key_via_parent": True,
                    "link_class": "KEVENd",
                },
                {
                    "xpath": "//button[@class='rBl3me' and @jsname='sIoYce']",
                    "key_attr": "data-icl-uuid",
                    "key_via_parent": False,
                    "link_class": "NDNGvf",
                },
            ],
        }

        configs = BUTTON_CONFIGS["ai_mode" if search_params.ai_mode else "standard"]

        # Resolve which config/buttons to use
        target_buttons, link_class = [], None
        for config in configs:
            all_buttons = self.driver.find_elements(By.XPATH, config["xpath"])
            visible = [b for b in all_buttons if b.is_displayed()]
            if visible:
                target_buttons = visible
                link_class = config["link_class"]
                active_config = config
                print(f"Found {len(visible)} visible buttons via: {config['xpath']}")
                break

        if not target_buttons:
            print("No visible buttons found. Process complete.")
            return content_data

        for button in target_buttons:
            try:
                # Extract key
                if active_config["key_via_parent"]:
                    key = button.find_element(By.XPATH, "./..").get_attribute(active_config["key_attr"])
                else:
                    key = button.get_attribute(active_config["key_attr"])

                if not key or key in processed_buttons:
                    continue

                # Scroll, click
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button
                )
                time.sleep(0.2)

                try:
                    WebDriverWait(self.driver, max_wait_time).until(EC.element_to_be_clickable(button))
                    button.click()
                except ElementClickInterceptedException:
                    self.driver.execute_script("arguments[0].click();", button)

                time.sleep(0.5)

                # Scrape visible links
                try:
                    WebDriverWait(self.driver, max_wait_time).until(
                        lambda d: d.find_elements(By.CLASS_NAME, link_class)
                    )
                    visible_links = [
                        l for l in self.driver.find_elements(By.CLASS_NAME, link_class)
                        if l.is_displayed()
                    ]
                    urls = [l.get_attribute("href") for l in visible_links if l.get_attribute("href")]
                    content_data[key] = urls
                    print(f"Extracted {len(urls)} URLs for key: {key}")
                except TimeoutException:
                    print(f"No {link_class} links found for key: {key}")
                    content_data[key] = []

                processed_buttons.add(key)
                time.sleep(random.uniform(0.05, 0.15))

            except Exception as e:
                print(f"Error processing button {key}: {e}")

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
