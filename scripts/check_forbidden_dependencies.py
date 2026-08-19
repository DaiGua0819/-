from pathlib import Path

FORBIDDEN = {
    "playwright-stealth",
    "browserforge",
    "patchright",
    "undetected-chromedriver",
    "selenium-stealth",
    "2captcha",
    "anticaptcha",
    "proxy-rotator",
    "fingerprint",
    "captcha-solver",
}


def main() -> None:
    content = Path("pyproject.toml").read_text(encoding="utf-8").lower()
    found = sorted(name for name in FORBIDDEN if name in content)
    if found:
        raise SystemExit(f"发现禁止依赖: {', '.join(found)}")
    print("forbidden dependency scan passed")


if __name__ == "__main__":
    main()
