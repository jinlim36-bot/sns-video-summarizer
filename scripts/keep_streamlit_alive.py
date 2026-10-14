"""Visit the deployed app and verify that its Streamlit session is working."""
import os
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Error as PlaywrightError


def validate_app_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or not parsed.hostname
            or not parsed.hostname.endswith('.streamlit.app')
            or parsed.username or parsed.password or parsed.port
            or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
        raise ValueError('STREAMLIT_APP_URL must be an HTTPS Streamlit Cloud app URL.')
    return url.rstrip('/')


def visit_app(browser, url, title, session_seconds=60):
    context = browser.new_context()
    try:
        page = context.new_page()
        response = page.goto(url, wait_until='domcontentloaded', timeout=90000)
        if response is not None and response.status >= 400:
            raise RuntimeError(f'App returned HTTP {response.status}')
        heading = page.get_by_role('heading', name=title, exact=True)
        wake = page.get_by_role('button', name=re.compile(r'Yes, get this app back up|Wake.*app', re.I))
        deadline = time.monotonic() + 180
        wake_clicked = False
        while time.monotonic() < deadline:
            if heading.is_visible():
                break
            if not wake_clicked and wake.count() and wake.first.is_visible():
                wake.first.click(timeout=15000)
                wake_clicked = True
                print('Requested wake-up.')
            page.wait_for_timeout(2000)
        else:
            raise RuntimeError('App did not render its expected heading within 3 minutes.')
        # A rendered Streamlit widget verifies script execution, not just HTML/health.
        page.get_by_role('button', name='요약 시작하기', exact=True).wait_for(timeout=30000)
        page.wait_for_timeout(session_seconds * 1000)
        if not heading.is_visible():
            raise RuntimeError('App became unavailable during the browser session.')
        print('App rendered successfully; browser session remained open.')
    finally:
        context.close()


def main():
    url = validate_app_url(os.environ.get('STREAMLIT_APP_URL', ''))
    title = os.environ.get('STREAMLIT_APP_TITLE', '🎬 SNS 영상 AI 요약기')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for attempt in range(1, 4):
                try:
                    visit_app(browser, url, title)
                    return
                except (PlaywrightError, RuntimeError) as exc:
                    print(f'Attempt {attempt} failed: {exc}')
                    if attempt == 3:
                        raise
                    time.sleep(10)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
