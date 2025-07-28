from typing import List, Dict, Any
from tqdm import tqdm
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
import sys
import re
import random
import os
import time

from src.logger import log
from .base import BaseVideoProvider


class EnvatoProvider(BaseVideoProvider):
    """
    一个用于与 Envato Elements 交互的 Provider 类。
    封装了浏览器初始化、登录、搜索和下载等操作。
    """

    # --- 页面元素选择器 (从 config.py 迁移并作为类常量) ---
    login_page_cookie_accept_button_xpath = "//button[contains(text(),'Accept Cookies')]"
    login_username_field_id = "username"
    login_password_field_id = "password"
    login_submit_button_id = "sso-forms__submit"
    account_elements_redirect_link_xpath = "//a[contains(@href, 'to=elements')]"
    elements_homepage_cookie_accept_button_xpath = "//button[contains(text(),'Accept Cookies')]"
    search_input_css_selector = 'input[data-testid="search-form-input"]'
    item_card_generic_css_selector = 'div[data-testid="video-card"]'
    item_card_download_button_css_selector = 'button[data-testid="button-download"]'
    download_popup_add_download_button_xpath = "//button[@data-testid='add-download-button']"
    
    # 根据您提供的最新信息，这个 XPath 再次有效，所以我们将其放在首位
    # download_popup_license_radio_button_xpath_template = "//label[.//span[contains(text(), '{license_name}')]]"
    # 更正：license radio button xpath 应该最终点击的是 input
    # 假设这里的 {license_name} 应该与实际的 radio input 的 id 或者 value 对应
    # 您可能需要根据实际的Envato Elements页面来确认这里应该使用的许可证radio button的xpath。
    # 常见的模式是匹配包含文本的label下的radio：
    download_popup_license_radio_button_xpath_template = "//label[contains(.,'{license_name}')]//input[@type='radio']" 
    # 或者如果 {license_name} 是 Span 里的文本，那么这个可能更准确：
    # download_popup_license_radio_button_xpath_template = "//label[.//span[contains(text(), '{license_name}')]]//input[@type='radio']"

    download_resolution_dropdown_css_selector = 'select[data-testid="select-download-format"]'
    download_resolution_option_xpath_template = ".//option[contains(text(), '{resolution_text}')]"

    # 定义多个备用的标题 XPath 策略，按优先级从高到低排列
    # 策略 1: 基于 img/ancestor/following-sibling (您最新成功的 XPath)
    TITLE_XPATH_STRATEGIES = [
        "//div[@data-testid='modal-body']//img/ancestor::div[1]/following-sibling::div[1]//span[1]",
        # 策略 2: 更通用的 span 查找，排除文件大小信息，并找文本长度大于10的第一个
        "//div[@data-testid='modal-body']//span[string-length(normalize-space()) > 10 and not(contains(text(), 'MB')) and not(contains(text(), 'GB')) and not(contains(text(), 'KB'))][1]",
        # 策略 3: 最通用的 span 查找，只要在 modal-body 里面有文本的 span 就行 (可能会有误报)
        "//div[@data-testid='modal-body']//span[normalize-space() != ''][1]",
    ]

    def __init__(self, config: dict):
        super().__init__()
        envato_config = config.get('search_providers', {}).get('envato', {})
        paths_config = config.get('paths', {})

        self.chrome_driver_path = envato_config.get('chrome_driver_path')
        self.username = envato_config.get('username')
        self.password = envato_config.get('password')
        self.headless_mode = envato_config.get('headless_mode', False)
        self.wait_timeout = envato_config.get('wait_timeout', 20)
        self.license_name = envato_config.get('license_name', 'Gemini')
        self.target_resolutions = envato_config.get('target_resolutions', ['1080p', '2K'])
        self.enabled = envato_config.get('enabled', False)

        base_download_dir = paths_config.get(
            'local_assets_dir', 'storage/local')
        self.download_dir = os.path.join(base_download_dir, 'envato')

        if not all([self.chrome_driver_path, self.username, self.password]):
            raise ValueError(
                "Envato provider is not configured correctly. Please check your config.yaml under 'search_providers.envato'")

        if "YOUR_ENVATO_USERNAME" in self.username or "YOUR_ENVATO_PASSWORD" in self.password:
            log.warning(
                "Envato provider is using placeholder credentials. It will be disabled.")
            self.enabled = False
            return

        self.driver = self._initialize_browser()
        if not self.driver:
            self.enabled = False
            log.error("浏览器初始化失败，Envato provider 已被禁用。")
            return

        if not self.login():
            self.enabled = False
            log.error("Envato 登录失败，provider 已被禁用。")
            return

    def _initialize_browser(self):
        log.info("正在初始化浏览器...")
        options = webdriver.ChromeOptions()
        user_data_dir = os.path.join(os.getcwd(), "chrome_profile_envato")
        options.add_argument(f"--user-data-dir={user_data_dir}")
        log.info(f"使用用户数据目录: {user_data_dir}")

        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('--log-level=3')

        if self.headless_mode:
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            
        options.add_argument("--start-maximized")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-extensions")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--blink-settings=imagesEnabled=true")

        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
        prefs = {
            "download.default_directory": os.path.abspath(self.download_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safeBrowse.enabled": True
        }
        options.add_experimental_option("prefs", prefs)
        print(f"下载目录已配置为: {self.download_dir}")

        try:
            service = Service(os.path.abspath(self.chrome_driver_path))
            driver = webdriver.Chrome(service=service, options=options)
            log.info("浏览器初始化完成。")
            return driver
        except Exception as e:
            log.error(f"浏览器初始化失败: {e}")
            return None

    def check_login_status(self):
        log.info("正在检查登录状态...")
        try:
            self.driver.get("https://elements.envato.com/")
            wait = WebDriverWait(self.driver, 10)
            avatar_button_selector = (
                By.CSS_SELECTOR, 'button[data-testid="account-avatar"]')
            wait.until(EC.presence_of_element_located(avatar_button_selector))
            log.info("检测到用户头像按钮，用户已登录。")
            return True
        except TimeoutException:
            log.warning("未检测到用户头像按钮，用户未登录或登录已过期。")
            return False
        except Exception as e:
            log.error(f"检查登录状态时发生未知错误: {e}")
            return False

    def login(self):
        if self.check_login_status():
            log.info("\n检测到已登录，跳过登录步骤。")
            self._handle_optional_elements_cookies()
            return True

        log.info("需要登录。")
        log.info("开始登录 Envato Elements...")
        try:
            LOGIN_URL = "https://account.envato.com/sign_in"
            self.driver.get(LOGIN_URL)
            wait = WebDriverWait(self.driver, self.wait_timeout)

            try:
                accept_cookies_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, self.login_page_cookie_accept_button_xpath)))
                accept_cookies_button.click()
                log.info("已点击 'Accept Cookies' 按钮。")
            except (TimeoutException, NoSuchElementException):
                log.info("未找到登录页的 'Accept Cookies' 按钮或已接受。")

            username_field = wait.until(EC.presence_of_element_located((By.ID, self.login_username_field_id)))
            password_field = wait.until(EC.element_to_be_clickable((By.ID, self.login_password_field_id)))

            for char in self.username:
                username_field.send_keys(char)
                time.sleep(random.uniform(0.05, 0.2))
            time.sleep(random.uniform(0.5, 1.0))

            for char in self.password:
                password_field.send_keys(char)
                time.sleep(random.uniform(0.05, 0.2))
            log.info("已输入用户名和密码。")

            login_submit_button = wait.until(
                EC.element_to_be_clickable((By.ID, self.login_submit_button_id)))
            login_submit_button.click()
            log.info("已点击登录按钮。")

            wait.until(EC.staleness_of(login_submit_button),
                       message="登录按钮未在预期时间内消失。")
            log.info("登录表单已消失，页面正在重定向...")

            wait.until(EC.url_contains("account.envato.com/"))
            log.info(
                f"已成功重定向到 Envato Account 页面: {self.driver.current_url}")

            # 登录后直接导航到 Elements 主页，而不是寻找点击链接
            log.info("登录成功，直接导航到 Envato Elements 主页...")
            self.driver.get("https://elements.envato.com/")

            # 等待主页加载完成的标志，例如用户头像按钮
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'button[data-testid="account-avatar"]')))
            log.info("已成功导航到 Envato Elements 主页。")

            self._handle_optional_elements_cookies()
            log.success("登录并导航到目标页面成功！")
            return True

        except Exception as e:
            log.error(f"登录失败: {e}")
            log.error(f"当前 URL: {self.driver.current_url}")
            return False

    def _handle_optional_elements_cookies(self):
        log.info("检查 Envato Elements 主页上的可选 Cookie 弹窗...")
        wait = WebDriverWait(self.driver, 5)
        try:
            accept_cookies_button = wait.until(EC.element_to_be_clickable(
                (By.XPATH, self.elements_homepage_cookie_accept_button_xpath)))
            accept_cookies_button.click()
            log.info("已点击 Envato Elements 主页上的 'Accept Cookies' 按钮。")
        except (TimeoutException, NoSuchElementException):
            log.info("Envato Elements 主页上未找到或无需点击 Cookie 弹窗。")

    def search(self, keywords: List[str], count: int = 1, min_duration: float = 0) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []

        query = " ".join(keywords)
        if not self.search_on_envato(query):
            return []

        downloaded_files = self.download_videos(
            # num_to_download=count, license_name=self.license_name, target_resolutions=self.target_resolutions)
            num_to_download=count, license_name=self.license_name, target_resolutions=self.target_resolutions)

        standardized_videos = []
        for file_path in downloaded_files:
            video_name = os.path.basename(file_path)
            standardized_videos.append({
                'id': f"envato-{video_name}",
                'video_name': video_name,
                'download_url': f"file://{os.path.abspath(file_path)}",
                'local_path': file_path,
                'source': 'envato',
                'description': f"Video from Envato Elements: {video_name}"
            })
        return standardized_videos

    def search_on_envato(self, search_query, item_type_path="stock-video"):
        log.info(f"开始搜索：'{search_query}'，类型路径：'{item_type_path}'")
        wait = WebDriverWait(self.driver, self.wait_timeout)
        try:
            formatted_query = search_query.replace(' ', '+')
            target_search_url = f"https://elements.envato.com/{item_type_path}/{formatted_query}/orientation-horizontal/resolution-1080p-(full-hd)+720p-(hd)+2k"
            log.info(f"导航到搜索结果页面: {target_search_url}")
            self.driver.get(target_search_url)
            wait.until(EC.url_contains(f"/{item_type_path}/{formatted_query}"))
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, self.search_input_css_selector)))
            log.info("搜索结果页面加载完成。")
            return True
        except Exception as e:
            log.error(f"执行搜索失败: {e}")
            return False

    def download_videos(self, num_to_download=1, license_name="Commercial Use", target_resolutions=None, download_complete_timeout=3600):
        log.info(f"\n开始下载最多 {num_to_download} 个素材...")
        wait = WebDriverWait(self.driver, self.wait_timeout)
        downloaded_files = []
        try:
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, self.item_card_generic_css_selector)))
            item_cards = self.driver.find_elements(
                By.CSS_SELECTOR, self.item_card_generic_css_selector)
            if not item_cards:
                log.warning("未找到任何素材卡片。")
                return []

            log.info(f"找到 {len(item_cards)} 个素材卡片。")
            items_to_process = item_cards[:num_to_download]

            for i, item_card in enumerate(items_to_process):
                log.info(f"\n尝试下载第 {i+1} 个素材...")
                try:
                    files_before_download = set(os.listdir(self.download_dir))
                    log.debug(f"下载前目录文件快照: {files_before_download}")

                    # 尝试重新定位当前素材卡片，以避免 StaleElementReferenceException
                    # 这是处理动态页面的常见做法
                    # 重新查找所有元素，并根据索引获取当前卡片
                    refreshed_item_cards = wait.until(EC.presence_of_all_elements_located(
                        (By.CSS_SELECTOR, self.item_card_generic_css_selector)))
                    current_item_card = refreshed_item_cards[i]

                except (IndexError, StaleElementReferenceException, TimeoutException) as e:
                    log.warning(
                        f"WARNING: 无法重新定位第 {i+1} 个素材卡片。错误: {e}")
                    self.driver.refresh()
                    time.sleep(3)
                    continue

                actual_downloaded_filename = self._download_single_item(
                    current_item_card, license_name, target_resolutions, download_complete_timeout, files_before_download)

                if actual_downloaded_filename:
                    # 创建按天组织的子目录
                    today_str = time.strftime("%Y-%m-%d")
                    daily_dir = os.path.join(self.download_dir, today_str)
                    os.makedirs(daily_dir, exist_ok=True)

                    # 将下载的文件移动到当天的目录
                    source_path = os.path.join(
                        self.download_dir, actual_downloaded_filename)
                    destination_path = os.path.join(
                        daily_dir, actual_downloaded_filename)

                    try:
                        os.rename(source_path, destination_path)
                        downloaded_files.append(destination_path)
                        log.success(
                            f"第 {i+1} 个素材下载成功并移动到: {destination_path}")
                        # 成功下载一个后，立即返回，不再继续下载
                        return downloaded_files
                    except OSError as e:
                        log.error(
                            f"移动文件 {actual_downloaded_filename} 失败: {e}")

                else:
                    log.error(f"第 {i+1} 个素材下载失败，跳过。")
                    self.driver.refresh()
                    time.sleep(3)

                if len(downloaded_files) < num_to_download and (i + 1) < len(items_to_process):
                    time.sleep(random.uniform(2, 5))

            return downloaded_files
        except Exception as e:
            log.error(f"遍历下载素材时发生错误: {e}")
            return downloaded_files
    
    def _download_single_item(self, item_element, license_name, target_resolutions, timeout, files_before_download):
        wait = WebDriverWait(self.driver, self.wait_timeout)
        downloaded_filename_prefix = None  # 初始化为None

        try:
            download_button = item_element.find_element(By.CSS_SELECTOR, self.item_card_download_button_css_selector)
            action = ActionChains(self.driver)
            action.move_to_element(item_element).perform()
            wait.until(EC.visibility_of(download_button))
            wait.until(EC.element_to_be_clickable(download_button))
            
            self.driver.execute_script("arguments[0].click();", download_button)
            log.info(f"已点击下载按钮。等待下载弹窗...")

            WebDriverWait(self.driver, max(self.wait_timeout, 15)).until(
                EC.presence_of_element_located((By.XPATH, self.download_popup_add_download_button_xpath)))
            log.info("下载弹窗已出现。")

            raw_title = None
            for strategy_xpath in self.TITLE_XPATH_STRATEGIES:
                try:
                    title_element = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, strategy_xpath)))
                    raw_title = title_element.text.strip()
                    log.info(
                        f"成功使用 XPath '{strategy_xpath}' 捕获到素材标题: '{raw_title}'")
                    break
                except (TimeoutException, NoSuchElementException) as e:
                    log.warning(
                        f"尝试 XPath '{strategy_xpath}' 失败: {e.msg.splitlines()[0]}")

            if raw_title:
                cleaned_title = re.sub(r'[\\/:*?"<>|]', '_', raw_title)
                downloaded_filename_prefix = cleaned_title
            else:
                log.error("警告: 无法从下载弹窗中获取素材标题，所有策略均失败。")
                downloaded_filename_prefix = "unknown_download"

            # --- 新增：检查素材是否已经下载过 ---
            if self._is_already_downloaded(downloaded_filename_prefix):
                log.info(
                    f"素材 '{downloaded_filename_prefix}' 已存在，跳过下载。")
                # 尝试关闭弹窗
                try:
                    ActionChains(self.driver).send_keys(
                        webdriver.common.keys.Keys.ESCAPE).perform()
                    time.sleep(1)  # 等待弹窗关闭
                except Exception as e:
                    log.warning(f"关闭弹窗时出错: {e}, 刷新页面以继续。")
                    self.driver.refresh()
                return None  # 返回 None 表示跳过

            # --- 在点击 License & download 前，检查并删除下载目录中可能存在的旧文件 ---
            # 确保在获取到下载前缀后执行此操作
            self._delete_existing_files(downloaded_filename_prefix)
            files_before_download = set(os.listdir(self.download_dir))
            log.debug(
                f"删除旧文件后，更新的下载前目录文件快照: {files_before_download}")


            if target_resolutions:
                self._select_resolution(target_resolutions)

            license_radio_button_xpath = self.download_popup_license_radio_button_xpath_template.format(
                license_name=license_name)
            license_option = wait.until(EC.element_to_be_clickable(
                (By.XPATH, license_radio_button_xpath)))
            license_option.click()
            log.info(f"已选择许可证 '{license_name}'。")

            license_and_download_button = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'button[data-testid="add-download-button"]')))
            license_and_download_button.click()
            log.info("已点击 'License & download' 按钮，开始下载。")

            # --- 等待下载完成，并尝试获取实际下载的文件名 ---
            actual_downloaded_filename = self._wait_for_download_and_get_filename(
                downloaded_filename_prefix, timeout, files_before_download)

            return actual_downloaded_filename

        except Exception as e:
            log.error(f"下载单个素材时发生错误: {e}")
            self.driver.refresh()
            return None

    # def _select_resolution(self, target_resolutions):
    #     log.info(f"检查是否存在分辨率选择器，优先级为: {target_resolutions}")
    #     try:
    #         resolution_select_element = WebDriverWait(self.driver, 5).until(
    #             EC.presence_of_element_located(
    #                 (By.CSS_SELECTOR, self.download_resolution_dropdown_css_selector))
    #         )
    #         select = Select(resolution_select_element)
    #         available_options = [opt.text for opt in select.options]

    #         for res in target_resolutions:
    #             for available_opt in available_options:
    #                 if res.lower() in available_opt.lower():
    #                     select.select_by_visible_text(available_opt)
    #                     log.success(f"已成功选择分辨率: '{available_opt}'")
    #                     return True # 表示成功选择

    #         log.warning(
    #             f"在可用选项 {available_options} 中未找到任何期望的分辨率 {target_resolutions}。将使用默认选项。")
    #         return False # 表示未选择，将使用默认

    #     except (TimeoutException, NoSuchElementException):
    #         log.info("未找到分辨率选择器，将使用默认分辨率。")
    #         return False # 表示未选择，将使用默认


    def _select_resolution(self, target_resolutions):
        log.info(f"检查是否存在分辨率选择器，优先级为: {target_resolutions}")
        try:
            resolution_select_element = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, self.download_resolution_dropdown_css_selector))
            )
            select = Select(resolution_select_element)
            available_options = [opt.text for opt in select.options]

            for res in target_resolutions:
                for available_opt in available_options:
                    if res.lower() in available_opt.lower():
                        select.select_by_visible_text(available_opt)
                        log.success(f"已成功选择分辨率: '{available_opt}'")
                        return True # 表示成功选择

            log.warning(
                f"在可用选项 {available_options} 中未找到任何期望的分辨率 {target_resolutions}。将使用默认选项。")
            return False # 表示未选择，将使用默认

        except (TimeoutException, NoSuchElementException):
            log.info("未找到分辨率选择器，将使用默认分辨率。")
            return False # 表示未选择，将使用默认
        
    def _delete_existing_files(self, filename_prefix):
        """
        根据文件名前缀删除下载目录（包括日期子目录）中可能存在的旧文件。
        """
        normalized_prefix = re.sub(
            r'[^a-zA-Z0-9\s]', '', filename_prefix).lower().replace(' ', '-')
        log.info(f"正在检查并删除与 '{normalized_prefix}' 相关的旧文件...")

        # 检查根目录和所有日期子目录
        dirs_to_check = [self.download_dir]
        for item in os.listdir(self.download_dir):
            full_path = os.path.join(self.download_dir, item)
            if os.path.isdir(full_path):
                dirs_to_check.append(full_path)

        for directory in dirs_to_check:
            for filename in os.listdir(directory):
                if normalized_prefix in filename.lower():
                    file_path = os.path.join(directory, filename)
                    if os.path.isfile(file_path):
                        try:
                            os.remove(file_path)
                            log.info(f"已删除旧文件: {file_path}")
                        except OSError as e:
                            log.error(f"删除文件 {file_path} 失败: {e}")
                    else:
                        log.debug(f"跳过目录: {filename}")
                    try:
                        os.remove(file_path)
                        log.info(f"已删除旧文件: {filename}")
                    except OSError as e:
                        log.error(f"删除文件 {filename} 失败: {e}")
                else:
                    log.debug(f"跳过目录: {filename}")

    def _wait_for_download_and_get_filename(self, filename_prefix, timeout, files_before_download):
        """
        等待文件下载完成，并返回最终的文件名。
        使用 tqdm 库显示下载进度条。
        """
        start_time = time.time()
        log.info(
            f"开始等待文件下载完成 (超时 {timeout} 秒)。预期前缀: '{filename_prefix}'")

        normalized_prefix = re.sub(
            r'[^a-zA-Z0-9\s]', '', filename_prefix).lower().replace(' ', '-')
        log.debug(
            f"标准化后的预期文件名部分（用于匹配）: '{normalized_prefix}'")

        found_crdownload_files = []
        pbar = tqdm(total=0, unit='B', unit_scale=True,
                    desc=f"下载 {filename_prefix[:30]}...", leave=False)
        last_reported_size = 0
        check_interval = 1

        while time.time() - start_time < timeout:
            current_files = os.listdir(self.download_dir)
            new_files_since_start = [
                f for f in current_files if f not in files_before_download]
            relevant_new_files = [
                f for f in new_files_since_start if normalized_prefix in f.lower()
            ]

            crdownload_file_found = False
            for f in relevant_new_files:
                if f.endswith(".crdownload"):
                    crdownload_file_found = True
                    if f not in found_crdownload_files:
                        pbar.set_description(f"下载 '{f}'")
                        found_crdownload_files.append(f)

                    current_file_path = os.path.join(self.download_dir, f)
                    try:
                        current_size_bytes = os.path.getsize(current_file_path)
                        size_increment = current_size_bytes - last_reported_size
                        if size_increment > 0:
                            pbar.update(size_increment)
                            last_reported_size = current_size_bytes
                    except OSError:
                        pass

                    potential_final_name = f[:-len(".crdownload")]
                    if potential_final_name in current_files:
                        final_size_bytes = os.path.getsize(
                            os.path.join(self.download_dir, potential_final_name))
                        if pbar.total == 0 or final_size_bytes > pbar.n:
                            pbar.update(final_size_bytes - pbar.n)
                        pbar.close()
                        log.success(
                            f"检测到临时文件 '{f}' 已完成下载，最终文件: '{potential_final_name}'")
                        return potential_final_name
                    elif any(final_f for final_f in current_files if final_f.startswith(potential_final_name) and not final_f.endswith(".crdownload")):
                        for final_f in current_files:
                            if final_f.startswith(potential_final_name) and not final_f.endswith(".crdownload"):
                                final_size_bytes = os.path.getsize(
                                    os.path.join(self.download_dir, final_f))
                                if pbar.total == 0 or final_size_bytes > pbar.n:
                                    pbar.update(final_size_bytes - pbar.n)
                                pbar.close()
                                log.success(
                                    f"检测到临时文件 '{f}' 已完成下载，最终文件（含序号）: '{final_f}'")
                                return final_f

            if not crdownload_file_found:
                for f in relevant_new_files:
                    if not f.endswith(".crdownload"):
                        final_size_bytes = os.path.getsize(
                            os.path.join(self.download_dir, f))
                        if pbar.total == 0 or final_size_bytes > pbar.n:
                            pbar.update(final_size_bytes - pbar.n)
                        pbar.close()
                        log.success(f"直接检测到已下载的完整文件: {f}")
                        return f

                for f in new_files_since_start:
                    if not f.endswith(".crdownload"):
                        final_size_bytes = os.path.getsize(
                            os.path.join(self.download_dir, f))
                        if pbar.total == 0 or final_size_bytes > pbar.n:
                            pbar.update(final_size_bytes - pbar.n)
                        pbar.close()
                        log.warning(
                            f"警告：未找到匹配前缀的临时文件，但检测到新下载文件：{f}。此文件可能不完全匹配预期前缀，但可能是唯一的新下载文件。")
                        return f

            time.sleep(check_interval)

        pbar.close()
        log.error(f"在 {timeout} 秒内未检测到文件下载完成。")
        return None

    def close(self):
        if self.driver:
            log.info("正在关闭浏览器...")
            self.driver.quit()
            self.driver = None
            log.info("浏览器已关闭。")

    def _is_already_downloaded(self, filename_prefix: str) -> bool:
        """
        检查具有给定前缀的文件是否已存在于下载目录或其日期子目录中。
        """
        normalized_prefix = re.sub(
            r'[^a-zA-Z0-9\s]', '', filename_prefix).lower().replace(' ', '-')

        dirs_to_check = [self.download_dir]
        if os.path.exists(self.download_dir):
            for item in os.listdir(self.download_dir):
                full_path = os.path.join(self.download_dir, item)
                if os.path.isdir(full_path):
                    dirs_to_check.append(full_path)

        for directory in dirs_to_check:
            if os.path.exists(directory):
                for filename in os.listdir(directory):
                    if normalized_prefix in filename.lower():
                        return True
        return False

    def __del__(self):
        self.close()
