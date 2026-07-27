import asyncio
import os
import re
import time
import urllib.parse
from playwright.async_api import async_playwright
import markdownify

async def process_article(context, sogou_title, url, save_dir, sem):
    async with sem:
        new_page = await context.new_page()
        try:
            print(f"正在访问: {sogou_title}")
            await new_page.goto(url, wait_until='domcontentloaded', timeout=20000)

            await new_page.wait_for_selector('#js_content, #js_access_msg, .weui-msg', timeout=15000)

            migrated_btn = await new_page.query_selector('#js_access_msg')
            if migrated_btn:
                transfer_url = await migrated_btn.get_attribute('href')
                if transfer_url:
                    transfer_url = transfer_url.replace('&amp;', '&')
                    print(f"检测到迁移，追溯新链接: {sogou_title}")
                    await new_page.goto(transfer_url, wait_until='domcontentloaded', timeout=20000)
                    await new_page.wait_for_selector('#js_content, .weui-msg', timeout=15000)

            body_text = await new_page.inner_text('body', timeout=5000)
            if any(kw in body_text for kw in ("该内容已被发布者删除", "此内容因违规无法查看", "已被删除", "参数错误")):
                print(f"跳过，内容已删除或违规: {sogou_title}")
                return

            content_element = await new_page.query_selector('#js_content')
            if not content_element:
                print(f"找不到正文: {sogou_title}")
                return

            html_content = await content_element.inner_html()
            md_content = markdownify.markdownify(html_content, heading_style="ATX")

            safe_title = re.sub(r'[\\/*?:"<>|]', "", sogou_title).strip()
            file_path = os.path.join(save_dir, f"{safe_title}.md")

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# {sogou_title}\n\n**原始链接**: {url}\n\n---\n\n{md_content}")

            print(f"已保存: {file_path}")

        except Exception as e:
            print(f"抓取失败 [{sogou_title}]: {e}")
        finally:
            await new_page.close()

async def scrape_sogou_weixin(keyword, pages=3):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        search_page = await context.new_page()

        save_dir = 'wechat_articles'
        os.makedirs(save_dir, exist_ok=True)

        sem = asyncio.Semaphore(7)
        encoded_keyword = urllib.parse.quote(keyword)

        for page_num in range(1, pages + 1):
            print(f"\n======== 搜索第 {page_num} 页 ========")
            search_url = f"https://weixin.sogou.com/weixin?type=2&query={encoded_keyword}&page={page_num}"
            await search_page.goto(search_url, wait_until='domcontentloaded')

            try:
                await search_page.wait_for_selector('.news-list', timeout=10000)
            except Exception:
                if "antispider" in search_page.url or "seccode" in search_page.url:
                    print(f"第 {page_num} 页遇到验证码，停止")
                else:
                    print("没有更多文章了")
                break

            article_elements = await search_page.query_selector_all('.news-list li .txt-box h3 a')
            print(f"第 {page_num} 页找到 {len(article_elements)} 篇文章")

            tasks = []
            for element in article_elements:
                sogou_title = (await element.inner_text()).strip().replace('\n', '')
                href = await element.get_attribute('href')
                url = f"https://weixin.sogou.com{href}" if href.startswith('/') else href
                tasks.append(asyncio.create_task(process_article(context, sogou_title, url, save_dir, sem)))

            await asyncio.gather(*tasks)

        print("\n全部抓取完成")
        await browser.close()

if __name__ == "__main__":
    start_time = time.time()
    asyncio.run(scrape_sogou_weixin("君赛生物融资", pages=3))
    elapsed = time.time() - start_time
    print(f"\n总耗时: {elapsed:.2f}秒")
