import time
import random
import os
from datetime import datetime, timezone

import orjson
import undetected_chromedriver as uc
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains

from .. import utils
from ..models.configs import SeleniumConfig
from ..models.data import ResponseOutput
from ..models.searches import SearchParams


TRANSLATIONS = {
    "en": {
        "reject_all": "Reject all",
        "show_all": "Show all",
        "show_more": "Show more",
        "not_now": "Not now",
        "view_related": "View related links",
        "search": "Search"
    },
    "de": {
        "reject_all": "Alle ablehnen",
        "show_all": "Alle anzeigen",
        "show_more": "Mehr anzeigen",
        "not_now": "Jetzt nicht",
        "view_related": "Zugehörige Links ansehen",
        "search": "Suche"
    },
    "es": {
        "reject_all": "Rechazar todo",
        "show_all": "Mostrar todo",
        "show_more": "Mostrar todo",
        "not_now": "Ahora no",
        "view_related": "Ver enlaces relacionados",
        "search": "Buscar"
    },
    "pt-BR": {
        "reject_all": "Rejeitar tudo",
        "show_all": "Mostrar tudo",
        "show_more": "Mostrar mais",
        "not_now": "Agora não",
        "view_related": "Ver links relacionados",
        "search": "Pesquisar"
    },
    "hy": {
        "show_all": "Ցույց տալ բոլորը",
        "show_more": "Ցույց տալ բոլոր առնչվող հղումները",
        "search": "Գտնել",
        "not_now": "NA",
        "reject_all": "Մերժել բոլորը",
    },
    "ru": {
        "show_all": "Показать все",
        "show_more": "Развернуть",
        "search": "Найти",
        "reject_all": 'Отклонить все',
        "not_now": ''
    },
    "fr": {
        "reject_all": "Tout refuser",
        "show_all": "Alle anzeigen",
        "show_more": "Mehr anzeigen",
        "not_now": "Jetzt nicht",
        "view_related": "Zugehörige Links ansehen",
        "search": "Suche"
    },
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
        self.debug = True

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
            print(search_params.url)
            self.driver.get(search_params.url)
            time.sleep(2)

            # Do basic page elements load
            if search_params.ai_mode:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "textarea.ITIRGe"))
                )
            else:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "search"))
                )
            

            time.sleep(2)
            response_output.html = self.driver.page_source
            response_output.url = self.driver.current_url
            response_output.response_code = 200
            response_output.interactive_data = {}

            # Expand AI overview if requested
            if search_params.ai_expand:
                expanded_html = self.expand_ai_overview(search_params)
                if expanded_html:
                    len_diff = len(expanded_html) - len(response_output.html)
                    self.log.debug(f"SERP | expanded html | len diff: {len_diff}")
                    response_output.html = expanded_html
                    citation_data = self.collect_citations(search_params)
                response_output.interactive_data['citations'] = citation_data

            if not search_params.ai_mode:
                response_output.interactive_data['auto'], response_output.interactive_data['auto_space'] = self.collect_autosuggest(search_params)
            else:
                response_output.interactive_data['auto'], response_output.interactive_data['auto_space'] = None, None

        except Exception as e:
            self.log.exception(f"SERP | Chromedriver error | {str(e)}")
        finally:
            self.delete_cookies()

        self.cleanup()
        return response_output

    def dbg(self, *args):
        if self.debug:
            print("[expanding SERP]", *args)

    def try_click(self, xpath, timeout=1):
        self.dbg(f"Attempting click: {xpath}")
        try:
            el = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            el.click()
            self.dbg(f"Click succeeded: {xpath}")
            return el
        except Exception as e:
            # self.dbg(f"Click failed: {xpath} — {type(e).__name__}: {e}")
            self.dbg(f"Click failed: {xpath} — {type(e).__name__}")
            return None

    def expand_ai_overview(self, search_params):
        """Expand AI overview box by clicking it
        Somewhat gratuitous expansion to this function,
        compatible with AI Mode windows. Possibly deprecated."""

        t = TRANSLATIONS[search_params.lang]
        XPATHS = {
            "reject_all": f"//button[.//div[normalize-space(.)='{t['reject_all']}']]",
            "show_more_aioverview": "//div[@jsname='rPRdsc' and @role='button']",
            "show_all_aimode": f"//div[@role='button' and .//span[normalize-space(.)='{t['show_all']}']]",
            "show_all_aioverview": f"//div[@role='button' and .//span[normalize-space(.)='{t['show_all']}']]",
            "not_now": f"//g-raised-button[@role='button' and .//div[normalize-space(.)='{t['not_now']}']]",
        }

        debug = True
        source = self.driver.page_source

        self.dbg(f"ai_mode={search_params.ai_mode}")

        self.dbg("Checking for reject_all button...")
        rejected = self.try_click(XPATHS["reject_all"])
        self.dbg(f"reject_all result: {'clicked' if rejected else 'not found/skipped'}")

        if search_params.ai_mode:
            self.dbg("Branch: AI mode")

            self.dbg("Checking for show_all button...")
            showed = self.try_click(XPATHS["show_all_aimode"])
            self.dbg(f"show_all result: {'clicked' if showed else 'not found/skipped'}")

            self.dbg("Grabbing page source...")
            source = self.driver.page_source
            self.dbg(f"Page source length: {len(source)} chars")
            return source

        # Standard (non-AI mode) expansion
        self.dbg("Branch: standard mode")
        expanded_source = None

        self.dbg("Checking for not_now button...")
        if self.try_click(XPATHS["not_now"]):
            self.dbg("not_now clicked, sleeping 2s...")
            time.sleep(2)
            expanded_source = self.driver.page_source
            self.dbg(f"Page source grabbed after not_now: {len(expanded_source)} chars")

        self.dbg("Checking for show_more button...")
        if self.try_click(XPATHS["show_more_aioverview"]):
            self.dbg("show_more clicked, sleeping 2s...")
            time.sleep(2)
            self.dbg("Checking for show_all after show_more...")
            self.try_click(XPATHS["show_all_aioverview"])
            expanded_source = self.driver.page_source
            self.dbg(f"Page source grabbed after show_more: {len(expanded_source)} chars")

        # self.response_output.interactive_data['ai_overview_success'] = expanded_source is not None           
        if expanded_source is None:
            self.dbg(f"No AI Overview detected. Returning source: {'None' if source is None else f'{len(source)} chars'}")
            return source

        self.dbg(f"Returning source: {'None' if expanded_source is None else f'{len(expanded_source)} chars'}")
        return expanded_source

    def collect_citations(self, search_params, max_wait_time=2):
        """Collect citation URLs by clicking each source button and scraping visible links."""

        content_data = {}
        processed_buttons = set()
        processed_keys = set()
        skip_reasons = {}
        
        t = TRANSLATIONS[search_params.lang]
        BUTTON_CONFIGS = {
            "ai_mode": [
                {
                    "xpath": "//button[contains(@class, 'vDOt8c')]",                   
                    "key_attr": "data-icl-uuid",
                    "key_via_parent": False,
                    "link_class": '//li[@class="Gzwrb"]//a',
                    "hover": True
                },
                {
                    "xpath": '//button[@aria-label="View related links"]',
                    "key_attr": "data-icl-uuid",
                    "key_via_parent": False,
                    "link_class": "//a[contains(@class, 'NDNGvf')]",
                    "hover": False
                },
                {
                    "xpath": "//button[contains(@class, 'rBl3me') and @data-amic='true' and @data-icl-uuid]",
                    "key_attr": "data-icl-uuid",
                    "key_via_parent": False,
                    "link_class": "//a[contains(@class, 'NDNGvf')]",
                    "hover": False
                },
            ],
            "standard": [
                {
                    "xpath": "//button[contains(@class, 'vDOt8c')]",                   
                    "key_attr": "data-icl-uuid",
                    "key_via_parent": False,
                    "link_class": '//li[@class="Gzwrb"]//a',
                    "hover": True
                },
                {
                    "xpath": "//div[@role='button' and @jsname='HtgYJd'] | //span[@role='button' and @jsname='HtgYJd']",
                    "key_attr": "data-cid",
                    "key_via_parent": True,
                    "link_class": "KEVENd",
                    "hover": False
                },
                {
                    # "xpath": "//button[@class='rBl3me' and @jsname='sIoYce']",
                    "xpath": "//button[contains(@class, 'rBl3me')] | //button[contains(@class, 'vDOt8c oy7Apc qu4n2c')]",                    
                    "key_attr": "data-icl-uuid",
                    "key_via_parent": False,
                    "link_class": "//a[contains(@class, 'NDNGvf')]",
                    "hover": False
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
                return True
            except Exception:
                return False

        def dismiss_hover():
            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass

        def get_button_by_key(xpath, key_attr, key_via_parent, key):
            for b in self.driver.find_elements(By.XPATH, xpath):
                try:
                    k = b.find_element(By.XPATH, "./..").get_attribute(key_attr) if key_via_parent \
                        else b.get_attribute(key_attr)
                    if k == key:
                        return b
                except Exception:
                    continue
            return None

        mode = "ai_mode" if search_params.ai_mode else "standard"
        configs = BUTTON_CONFIGS[mode]

        target_buttons, link_class, active_config = [], None, None
        for config in configs:
            all_buttons = self.driver.find_elements(By.XPATH, config["xpath"])
            visible = [b for b in all_buttons if b.is_displayed()]
            if visible:
                target_buttons, link_class, active_config = visible, config["link_class"], config
                break

        if not target_buttons:
            self.dbg("No visible buttons found across all configs.")
            return content_data

        keyed = []
        for b in target_buttons:
            try:
                key = (b.find_element(By.XPATH, "./..").get_attribute(active_config["key_attr"])
                       if active_config["key_via_parent"] else b.get_attribute(active_config["key_attr"]))
                if key:
                    keyed.append(key)
            except Exception:
                continue
        keyed = list(dict.fromkeys(keyed))

        self.dbg(f"Processing {len(keyed)} buttons (mode={mode})...")

        for i, key in enumerate(keyed):
            self.dbg(f"--- Button {i + 1}/{len(keyed)} | key={key} ---")
            if key in processed_keys:
                continue

            button = get_button_by_key(active_config["xpath"], active_config["key_attr"],
                                        active_config["key_via_parent"], key)
            if button is None:
                skip_reasons[key] = "button not found on re-query (DOM changed)"
                self.dbg(f"[{key}] SKIP: {skip_reasons[key]}")
                continue

            try:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});", button
                )
                time.sleep(0.15)  # small settle buffer for scroll, kept intentionally small

                t0 = time.time()
                if active_config["hover"]:
                    ActionChains(self.driver).move_to_element(button).perform()
                else:
                    try:
                        WebDriverWait(self.driver, max_wait_time).until(EC.element_to_be_clickable(button))
                        button.click()
                    except ElementClickInterceptedException:
                        self.dbg(f"[{key}] click intercepted, falling back to JS click.")
                        self.driver.execute_script("arguments[0].click();", button)

                # Wait for the flyout's links to become visible (state-based, not a fixed sleep)
                try:
                    WebDriverWait(self.driver, max_wait_time).until(
                        lambda d: any(l.is_displayed() for l in d.find_elements(By.XPATH, link_class))
                    )
                    wait_time = time.time() - t0
                    all_links = self.driver.find_elements(By.XPATH, link_class)
                    visible_links = [l for l in all_links if l.is_displayed()]
                    urls = [l.get_attribute("href") for l in visible_links if l.get_attribute("href")]
                    content_data[key] = urls
                    self.dbg(f"[{key}] captured {len(urls)} URL(s) after {wait_time:.2f}s")
                except TimeoutException:
                    skip_reasons[key] = f"no visible links after {max_wait_time}s wait"
                    content_data[key] = []
                    self.dbg(f"[{key}] SKIP: {skip_reasons[key]}")

                if active_config["hover"]:
                    dismiss_hover()
                else:
                    if not try_close_dialog():
                        self.dbg(f"[{key}] close-dialog button not found (may already be closed).")

                processed_keys.add(key)
                time.sleep(random.uniform(0.05, 0.15))

            except StaleElementReferenceException:
                skip_reasons[key] = "stale element reference"
                self.dbg(f"[{key}] SKIP: {skip_reasons[key]}")
                continue
            except Exception as e:
                skip_reasons[key] = f"{type(e).__name__}: {e}"
                self.dbg(f"[{key}] SKIP: unhandled error — {skip_reasons[key]}")
                try_close_dialog()
                dismiss_hover()

        self.dbg(f"Done. {len(content_data)}/{len(keyed)} keys processed, "
                  f"{sum(1 for v in content_data.values() if v)} with links.")
        if skip_reasons:
            self.dbg(f"{len(skip_reasons)} key(s) had issues:")
            for k, reason in skip_reasons.items():
                self.dbg(f"  {k}: {reason}")

        return content_data

    def collect_autosuggest(self, search_params):

        mode = "ai_mode" if search_params.ai_mode else "standard"
        if mode == 'ai_mode':
            return []

        auto = []
        auto_space = []

        t = TRANSLATIONS[search_params.lang]
        search_box_xpath = f"//textarea[@aria-label='{t['search']}']"
        search_box = self.driver.find_element(By.XPATH, search_box_xpath)
        # self.driver.execute_script(
        #     "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", search_box
        #     )
        self.driver.execute_script("window.scrollTo({top: 0, behavior: 'smooth'});")
        time.sleep(1)
        search_box = self.try_click(search_box_xpath)
        search_box.send_keys(Keys.END)  # Move cursor to end of existing text


        pause = random.uniform(.5, 1.5)
        self.dbg(f"Pausing {pause:.2f}s before first search box...")
        time.sleep(pause)

        def classify_li(li):
            classes = set(li.get_attribute("class").split())
            text = li.text.strip()
            if not text:
                return None

            base = {
                "text": text,
                "order": None,  # filled in by caller
            }

            if {"li", "sbct", "PZPZlf", "sbre"} <= classes and "yMAEcf" not in classes:
                return {**base, "type": "suggestion_entity"}
            elif {"li", "sbct", "PZPZlf", "yMAEcf"} <= classes:
                return {**base, "type": "question"}
            elif {"li", "sbct", "PZPZlf"} <= classes:
                return {**base, "type": "suggestion"}
            elif {"IDVnvc", "PZPZlf", "sbre"} <= classes:
                return {**base, "type": "entity"}
            elif "PZPZlf" in classes:
                return {**base, "type": "other"}
            elif 'sbct' in classes:
                return {**base, "type": "suggestion_ending"}

            return None

        def collect_matching_divs():
            results = []
            try:
                # container = self.driver.find_element(By.CLASS_NAME, "mkHrUc")
                container = self.driver.find_element(By.CLASS_NAME, "aajZCb")
                lis = container.find_elements(By.XPATH, ".//li[contains(@class, 'PZPZlf') or contains(@class, 'sbct')]")
                for order, li in enumerate(lis):
                    entry = classify_li(li)
                    if entry:
                        entry["order"] = order
                        results.append(entry)
                        self.dbg(f"Entry found: {entry}")
            except Exception as e:
                print(f"[collect_matching_divs] Error: {e}")
            return results

        # First pass
        first_pass = collect_matching_divs()
        auto.extend(first_pass)

        # Enter space and wait for suggestions to refresh
        search_box.send_keys(" ")

        pause = random.uniform(.5, 1.5)
        self.dbg(f"Pausing {pause:.2f}s before second search box...")
        time.sleep(pause)

        try:
            wait = WebDriverWait(self.driver, 3)
            if first_pass:
                stale_li = self.driver.find_elements(By.XPATH, ".//li[contains(@class, 'PZPZlf')]")
                if stale_li:
                    wait.until(EC.staleness_of(stale_li[0]))
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "mkHrUc")))
        except Exception:
            pass  # Suggestions may not change — continue anyway

        # Second pass
        second_pass = collect_matching_divs()
        auto_space.extend(second_pass)

        self.dbg(f"First pass, {len(auto)} auto results, Second pass {len(auto_space)} auto results")

        return auto, auto_space

    def cleanup(self) -> bool:
        """Clean up resources, particularly Selenium's browser instance

        Returns:
            bool: True if cleanup was successful or not needed, False if cleanup failed
        """
        print('Running cleanup')
        if self.driver:
            try:
                self.delete_cookies()
                self.close_all_windows()
                service_process = getattr(self.driver, "service", None)
                service_process = getattr(service_process, "process", None)
                self.driver.quit()
                try:
                    self.driver.command_executor.close()
                except Exception as e:
                    self.log.warning(f"Failed to close command executor: {e}")

                if service_process is not None:
                    # Close the parent-side pipe fds Popen opened for the
                    # chromedriver subprocess's stdin/stdout/stderr — quit()
                    # kills the child process but never closes these.
                    for stream in (service_process.stdin, service_process.stdout, service_process.stderr):
                        if stream is not None:
                            try:
                                stream.close()
                            except Exception:
                                pass
                    try:
                        service_process.wait(timeout=5)
                    except Exception as e:
                        self.log.warning(f"chromedriver did not exit cleanly: {e}")

                # print('Quited driver')
                self.reap_zombie_children()
                # print('reaping zombies')
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

    def reap_zombie_children(self):
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break  # no more zombies to reap
            except ChildProcessError:
                break  # no children at all
            # print(f"Reaped zombie pid={pid} status={status}")
