import time
import os
import asyncio
import random
import logging
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import requests
import urllib.parse

from config import settings

logger = logging.getLogger(__name__)

class PMCDownloader:

    _user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.1 Safari/605.1.15",
        "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.101 Mobile Safari/537.36",
    ]

    def __init__(self, **kwargs):
        self._save_dir = settings.PDF_CACHE
        os.makedirs(self._save_dir, exist_ok=True)

        # 记录下载前的文件列表
        self._files_before_download = set(os.listdir(self._save_dir))

        chrome_options = Options()

        # 在生产环境中启用无头模式，但可通过参数控制
        headless = kwargs.get('headless', False)  # 默认禁用无头模式以便调试
        if headless:
            chrome_options.add_argument("--headless=new")  # 新版Chrome的无头模式

        # 设置常用窗口大小（即使非无头模式也设置）
        chrome_options.add_argument("--window-size=1920,1080")

        # 解决Chrome驱动问题的参数
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        # 绕过某些网站的机器人检测
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")

        # 随机选择User-Agent
        user_agent = random.choice(self._user_agents)
        chrome_options.add_argument(f'user-agent={user_agent}')

        # 重要：启用必要的权限
        chrome_options.add_argument("--allow-file-access-from-files")
        chrome_options.add_argument("--allow-running-insecure-content")

        # 下载设置 - 修复PDF下载首选项
        prefs = {
            "download.default_directory": os.path.abspath(self._save_dir),  # 使用绝对路径
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True,  # 关键设置：强制下载PDF而不是在浏览器中打开
            "profile.default_content_settings.popups": 0,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            # 添加PDF处理和其他MIME类型设置
            "download.extensions_to_open": "",  # 清空此项，确保不会尝试打开PDF
            "download.open_pdf_in_system_reader": False,
            # 添加MIME类型处理
            "browser.helperApps.neverAsk.saveToDisk": "application/pdf,application/x-pdf"
        }
        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        try:
            service = Service(ChromeDriverManager().install())

            # remote chrome docker
            remote_chrome_url = f"http://{settings.CHROME_HOST}:{settings.CHROME_PORT}/wd/hub"
            self.driver = webdriver.Chrome(command_executor=remote_chrome_url, service=service, options=chrome_options)
            self.driver.set_page_load_timeout(120)

            # 导航到一个初始页面，以避免直接请求PMC时的空白页问题
            self.driver.get("about:blank")
            time.sleep(1)

            # 设置一个通用的请求会话，用于直接下载
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': user_agent})

            logger.info("WebDriver initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing WebDriver: {e}", exc_info=True)
            logger.error("Please ensure Chrome is installed and ChromeDriver is accessible.")
            raise

    def _get_new_files(self):
        """获取下载目录中新增的文件"""
        current_files = set(os.listdir(self._save_dir))
        return current_files - self._files_before_download

    def _download_pdf_direct(self, url, pmc_id):
        """使用requests直接下载PDF"""
        try:
            logger.info(f"Attempting direct PDF download from: {url}")
            response = self.session.get(url, stream=True, timeout=60)

            if response.status_code == 200 and 'application/pdf' in response.headers.get('Content-Type', ''):
                pdf_path = os.path.join(self._save_dir, f"PMC{pmc_id}.pdf")

                with open(pdf_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                logger.info(f"Successfully downloaded PDF directly to {pdf_path}")
                return pdf_path
            else:
                logger.warning(f"Direct download failed. Status: {response.status_code}, "
                               f"Content-Type: {response.headers.get('Content-Type')}")
                return None
        except Exception as e:
            logger.error(f"Error in direct PDF download: {e}")
            return None

    def _find_pdf_url(self):
        """查找页面中的PDF URL"""
        try:
            # 方法1: 尝试从当前页面识别PDF文件URL
            if self.driver.current_url.endswith('.pdf'):
                return self.driver.current_url

            # 方法2: 搜索所有链接中包含PDF的
            pdf_links = self.driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')]")
            direct_pdf_links = [link.get_attribute('href') for link in pdf_links
                                if link.get_attribute('href') and link.get_attribute('href').endswith('.pdf')]

            if direct_pdf_links:
                logger.info(f"Found direct PDF link: {direct_pdf_links[0]}")
                return direct_pdf_links[0]

            # 方法3: 检查页面源代码中是否有PDF链接
            page_source = self.driver.page_source.lower()
            pdf_indicators = [
                'href="',
                'data-url="',
                'src="'
            ]

            for indicator in pdf_indicators:
                start_pos = 0
                while True:
                    pos = page_source.find(indicator, start_pos)
                    if pos == -1:
                        break

                    start_url = pos + len(indicator)
                    end_url = page_source.find('"', start_url)
                    if end_url != -1:
                        potential_url = page_source[start_url:end_url]
                        if '.pdf' in potential_url:
                            # 构建完整URL
                            if potential_url.startswith('http'):
                                logger.info(f"Found PDF URL in page source: {potential_url}")
                                return potential_url
                            elif potential_url.startswith('/'):
                                base_url = urllib.parse.urlparse(self.driver.current_url)
                                full_url = f"{base_url.scheme}://{base_url.netloc}{potential_url}"
                                logger.info(f"Constructed PDF URL from relative path: {full_url}")
                                return full_url

                    start_pos = pos + len(indicator)

            # 如果没有找到任何PDF链接
            return None

        except Exception as e:
            logger.error(f"Error finding PDF URL: {e}")
            return None

    def pmc(self, pmc: str) -> dict:
        """下载指定PMC ID的论文PDF"""
        if not pmc.isdigit():
            return {
                'pmc': pmc,
                'error': f"Invalid PMC ID format: {pmc}",
                'source': 'PMC_Selenium',
            }

        # 构建PMC URL
        article_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc}/"
        pdf_url = f"{article_url}pdf/"  # 初始PDF URL猜测

        logger.info(f"Attempting to download PDF for PMC{pmc}")

        # 重置下载前文件列表
        self._files_before_download = set(os.listdir(self._save_dir))

        try:
            # 先访问文章页面
            logger.info(f"Navigating to article page: {article_url}")
            self.driver.get(article_url)
            time.sleep(5)  # 等待文章页面加载

            if "Page not found" in self.driver.page_source or "error" in self.driver.current_url.lower():
                logger.warning(f"Article page not found for PMC{pmc}. URL: {self.driver.current_url}")
                return {
                    'pmc': pmc,
                    'error': f"Article not found. URL: {self.driver.current_url}",
                    'source': 'PMC_Selenium',
                }

            logger.info(f"Article page loaded. Title: {self.driver.title}")

            # 多方法尝试下载PDF：

            # 方法1: 尝试查找并点击PDF链接
            try:
                # 优先尝试查找明确的PDF下载链接
                pdf_buttons = self.driver.find_elements(By.XPATH,
                                                        "//a[contains(text(), 'Download PDF') or contains(@title, 'Download PDF') or contains(@class, 'pdf-link')]")

                if pdf_buttons:
                    logger.info(f"Found PDF download button, clicking it...")
                    pdf_buttons[0].click()
                    time.sleep(8)  # 等待下载触发
                else:
                    # 备选: 查找一般PDF链接
                    pdf_links = self.driver.find_elements(By.XPATH,
                                                          "//a[contains(text(), 'PDF') or contains(@title, 'PDF') or contains(@href, 'pdf')]")

                    if pdf_links:
                        logger.info(f"Found {len(pdf_links)} PDF links on page")
                        # 点击第一个PDF链接
                        pdf_links[0].click()
                        logger.info("Clicked on PDF link")
                        time.sleep(8)  # 等待下载触发
                    else:
                        # 如果找不到链接，直接导航到PDF URL
                        logger.info(f"No PDF links found, directly navigating to PDF URL: {pdf_url}")
                        self.driver.get(pdf_url)
                        time.sleep(8)  # 等待页面加载
            except Exception as e:
                logger.warning(f"Error handling PDF link: {e}. Continuing with alternative methods.")

            # 方法2: 尝试识别页面中的PDF URL并直接下载
            pdf_link_url = self._find_pdf_url()
            if pdf_link_url:
                # 尝试直接下载
                direct_download_path = self._download_pdf_direct(pdf_link_url, pmc)
                if direct_download_path and os.path.exists(direct_download_path) and os.path.getsize(
                        direct_download_path) > 1000:
                    logger.info(f"Successfully downloaded PDF directly to {direct_download_path}")
                    return {
                        'pmc': pmc,
                        'filename': os.path.basename(direct_download_path),
                        'pdf_path': direct_download_path,
                        'source': 'PMC_Direct_Download',
                    }

            # 方法3: 尝试直接访问PMC的标准PDF URL
            if not self.driver.current_url.endswith('.pdf'):
                standard_pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc}/pdf/nihms-{pmc}.pdf"
                direct_download_path = self._download_pdf_direct(standard_pdf_url, pmc)
                if direct_download_path and os.path.exists(direct_download_path) and os.path.getsize(
                        direct_download_path) > 1000:
                    logger.info(f"Successfully downloaded PDF from standard URL to {direct_download_path}")
                    return {
                        'pmc': pmc,
                        'filename': os.path.basename(direct_download_path),
                        'pdf_path': direct_download_path,
                        'source': 'PMC_Standard_URL',
                    }

            # 检查下载结果 - 监控是否已通过Selenium下载了PDF
            download_wait_time_total = 90  # 总共等待下载的时间 (秒)
            check_interval = 3  # 每隔3秒检查一次
            downloaded_file_path = None

            logger.info(f"Monitoring downloads for up to {download_wait_time_total} seconds...")

            start_time = time.time()
            while time.time() - start_time < download_wait_time_total:
                # 检查是否有正在下载的文件
                active_downloads = [f for f in os.listdir(self._save_dir)
                                    if f.lower().endswith('.crdownload') or f.lower().endswith('.tmp')]

                if active_downloads:
                    logger.info(f"Active downloads detected: {active_downloads}")

                # 检查是否有新增的PDF文件
                new_files = self._get_new_files()
                pdf_files = [f for f in new_files if f.lower().endswith('.pdf')]

                if pdf_files:
                    # 找到最新下载的PDF文件
                    newest_pdf = max([os.path.join(self._save_dir, f) for f in pdf_files],
                                     key=os.path.getmtime)

                    # 检查文件大小
                    if os.path.getsize(newest_pdf) > 1000:  # 确保文件至少有1KB
                        # 如果没有正在下载的文件并且PDF大小合理，认为下载完成
                        if not active_downloads:
                            downloaded_file_path = newest_pdf
                            logger.info(f"Download complete: {downloaded_file_path} "
                                        f"({os.path.getsize(downloaded_file_path)} bytes)")
                            break
                        else:
                            logger.info(f"Found PDF {newest_pdf} but downloads still active. Waiting...")
                    else:
                        logger.warning(
                            f"Found PDF {newest_pdf} but size is only {os.path.getsize(newest_pdf)} bytes. Might be corrupted.")

                # 如果等待时间过长且没有下载活动，尝试其他方法
                if time.time() - start_time > 30 and not pdf_files and not active_downloads:
                    try:
                        # 再次检查当前页面中的可能的PDF链接
                        current_pdf_url = self._find_pdf_url()
                        if current_pdf_url:
                            logger.info(f"Found PDF URL after waiting: {current_pdf_url}")
                            direct_download_path = self._download_pdf_direct(current_pdf_url, pmc)
                            if direct_download_path and os.path.exists(direct_download_path) and os.path.getsize(
                                    direct_download_path) > 1000:
                                downloaded_file_path = direct_download_path
                                break

                        # 如果页面可能是PDF查看器，尝试打印为PDF
                        if "PDF" in self.driver.title or "/pdf/" in self.driver.current_url:
                            logger.info("Page appears to be a PDF viewer. Attempting to print to PDF...")
                            try:
                                # 使用Chrome的打印到PDF功能
                                print_options = {
                                    'landscape': False,
                                    'displayHeaderFooter': False,
                                    'printBackground': True,
                                    'preferCSSPageSize': True,
                                    'scale': 1,
                                }

                                pdf_data = self.driver.execute_cdp_cmd('Page.printToPDF', print_options)
                                if pdf_data and 'data' in pdf_data:
                                    import base64
                                    pdf_content = base64.b64decode(pdf_data['data'])

                                    # 保存PDF文件
                                    pdf_path = os.path.join(self._save_dir, f"PMC{pmc}.pdf")
                                    with open(pdf_path, 'wb') as pdf_file:
                                        pdf_file.write(pdf_content)

                                    logger.info(f"Successfully printed page to PDF: {pdf_path}")
                                    downloaded_file_path = pdf_path
                                    break
                            except Exception as e_print:
                                logger.error(f"Error printing to PDF: {e_print}")

                    except Exception as e:
                        logger.warning(f"Error in additional download attempts: {e}")

                time.sleep(check_interval)

            # 检查最终下载结果
            if downloaded_file_path and os.path.exists(downloaded_file_path):
                actual_filename = os.path.basename(downloaded_file_path)
                target_filename = f"PMC{pmc}.pdf"
                target_save_path = os.path.join(self._save_dir, target_filename)

                # 重命名文件
                if downloaded_file_path != target_save_path and not actual_filename.startswith(f"PMC{pmc}"):
                    try:
                        if os.path.exists(target_save_path):
                            logger.warning(f"Target file {target_save_path} already exists. "
                                           f"Keeping original name: {actual_filename}")
                        else:
                            os.rename(downloaded_file_path, target_save_path)
                            downloaded_file_path = target_save_path
                            actual_filename = target_filename
                            logger.info(f"Renamed file to {target_filename}")
                    except OSError as e_rename:
                        logger.error(f"Could not rename {downloaded_file_path} to {target_save_path}: {e_rename}")

                logger.info(f"Successfully downloaded PMC{pmc} PDF to: {downloaded_file_path}")
                return {
                    'pmc': pmc,
                    'filename': actual_filename,
                    'pdf_path': downloaded_file_path,
                    'source': 'PMC_Selenium',
                }
            else:
                # 最后尝试：使用Chrome的PDF打印功能生成PDF
                try:
                    logger.warning(f"No PDF download detected for PMC {pmc}. Trying to generate PDF from page...")

                    # 确保我们在正确的页面上
                    if "PDF" not in self.driver.title and "/pdf/" not in self.driver.current_url:
                        self.driver.get(pdf_url)
                        time.sleep(10)

                    print_options = {
                        'landscape': False,
                        'displayHeaderFooter': False,
                        'printBackground': True,
                        'preferCSSPageSize': True,
                        'scale': 1,
                    }

                    pdf_data = self.driver.execute_cdp_cmd('Page.printToPDF', print_options)
                    if pdf_data and 'data' in pdf_data:
                        import base64
                        pdf_content = base64.b64decode(pdf_data['data'])

                        # 保存PDF文件
                        pdf_path = os.path.join(self._save_dir, f"PMC{pmc}.pdf")
                        with open(pdf_path, 'wb') as pdf_file:
                            pdf_file.write(pdf_content)

                        logger.info(f"Successfully generated PDF from page: {pdf_path}")
                        return {
                            'pmc': pmc,
                            'filename': f"PMC{pmc}.pdf",
                            'pdf_path': pdf_path,
                            'source': 'PMC_Chrome_Print',
                        }
                except Exception as e_final:
                    logger.error(f"Final PDF generation attempt failed: {e_final}")

                # 如果所有方法都失败，截图页面
                screenshot_path = os.path.join(self._save_dir, f"PMC{pmc}_page.png")
                try:
                    self.driver.save_screenshot(screenshot_path)
                    logger.info(f"Page screenshot saved to {screenshot_path}")

                    return {
                        'pmc': pmc,
                        'error': f"PDF download failed but saved page screenshot to {screenshot_path}",
                        'screenshot_path': screenshot_path,
                        'current_url_at_error': self.driver.current_url,
                        'source': 'PMC_Selenium',
                    }
                except Exception as e_ss:
                    logger.error(f"Failed to save screenshot: {e_ss}")

                return {
                    'pmc': pmc,
                    'error': f"PDF download failed after all attempts.",
                    'current_url_at_error': self.driver.current_url,
                    'source': 'PMC_Selenium',
                }

        except Exception as e:
            logger.error(f"Error processing PMC {pmc}: {str(e)}", exc_info=True)
            current_url = "Unknown"
            try:
                current_url = self.driver.current_url
                screenshot_path = os.path.join(self._save_dir, f"PMC{pmc}_error.png")
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Error screenshot saved to {screenshot_path}")
            except:
                pass

            return {
                'pmc': pmc,
                'error': f"Processing error: {str(e)}",
                'current_url_at_error': current_url,
                'source': 'PMC_Selenium',
            }

    def close(self):
        """关闭WebDriver并释放资源"""
        if hasattr(self, 'driver'):
            try:
                self.driver.quit()
                logger.info("WebDriver closed successfully")
            except Exception as e:
                logger.error(f"Error closing WebDriver: {e}")


async def test_pmc_downloader():
    """测试函数，下载一个示例PMC论文"""
    try:
        # 使用非无头模式进行测试
        downloader = PMCDownloader(headless=False)

        # 可以尝试不同的PMC ID
        pmc_ids = ["7989091", "8965278", "7958527"]
        pmc_id = pmc_ids[0]

        logger.info(f"Testing PMC downloader with PMC{pmc_id}")
        result = downloader.pmc(pmc_id)

        logger.info(f"Download result: {result}")

        if 'error' in result:
            logger.error(f"Download failed: {result['error']}")
        else:
            logger.info(f"Download successful! File saved to: {result['pdf_path']}")

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
    finally:
        if 'downloader' in locals():
            downloader.close()


if __name__ == '__main__':
    asyncio.run(test_pmc_downloader())