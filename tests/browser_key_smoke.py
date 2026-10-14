from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from functools import partial
from playwright.sync_api import sync_playwright

handler = partial(SimpleHTTPRequestHandler, directory=str(Path(__file__).resolve().parents[1] / 'components' / 'api_key_store'))
server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}/'

def initialize(page):
    page.evaluate("window.postMessage({type:'streamlit:render'}, '*')")

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url)
        initialize(page)
        page.locator('#api-key').fill('test-credential-not-a-real-key')
        page.get_by_role('button', name='이 브라우저에 저장').click()
        page.get_by_text('저장된 키를 사용합니다.', exact=False).wait_for()
        assert page.locator('#api-key').input_value() == ''
        encrypted = page.evaluate("""async () => {
            const record = await access('readonly', store => store.get(RECORD));
            return !record.key.extractable && !JSON.stringify(record).includes('test-credential');
        }""")
        assert encrypted
        page.close()
        page = context.new_page()
        page.goto(url)
        page.evaluate("window.received=[]; window.addEventListener('message', e => {if(e.data.type==='streamlit:setComponentValue') window.received.push(e.data.value);})")
        initialize(page)
        page.get_by_text('저장된 키를 사용합니다.', exact=False).wait_for()
        assert page.evaluate('window.received[0].api_key') == 'test-credential-not-a-real-key'
        page.get_by_role('button', name='저장된 키 삭제').click()
        page.get_by_text('저장된 키를 삭제했습니다.', exact=True).wait_for()
        page.reload()
        initialize(page)
        page.wait_for_timeout(300)
        assert page.locator('#status').inner_text() == ''
        assert page.locator('#forget').is_hidden()
        context.close()
        browser.close()
        print('PASS: real browser encrypted save, restore in new page, and deletion')
finally:
    server.shutdown()
    server.server_close()
