from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("about:blank")
        browser.close()

    print("Local Playwright Chromium headless OK.")


if __name__ == "__main__":
    main()
