#!/usr/bin/env python3
"""
Flat AI infinite image generator/downloader.

Install:
    pip install selenium-driverless pillow piexif

Requires a Chromium/Google Chrome installation.

Default credentials:
    ./config.json
    {
      "username": "you@example.com",
      "password": "..."
    }

CLI credentials override config.json. The password is deliberately not written
to prompt.json or EXIF metadata.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import piexif
from PIL import Image

from selenium_driverless import webdriver
from selenium_driverless.types.by import By


GENERATOR_NAME = "Flat AI"
GENERATOR_URL = "https://flatai.org/ai-image-generator-free-no-signup/"
LOGIN_URL = "https://flatai.org/login/"
DEFAULT_CONFIG = "config.json"

ASPECT_RATIOS = ("1:1", "16:9", "4:3", "9:16", "3:4")

STYLES = (
    "Flat AI Ultra",
    "Flat AI Pro+",
    "Flat AI Pro",
    "Flat AI Base",
    "Standard",
    "Quality+",
    "Realistic",
    "Dark Fantasy",
    "Things",
    "Illustration",
    "Beauty Engine",
    "Film Noir",
    "Robot & Cyborg",
    "Retro Anime",
    "CGI Illustrations",
    "Instagramers",
    "Cyber Rooms",
    "Cinematic",
    "Flat Anime",
    "Real Skin",
    "Sci-fi Enviroments",
    "Mythic Fantasy",
    "Fantasy Armor",
    "Princess",
    "Daily life",
    "ColorART",
    "Mystical Realms",
    "Architectural",
    "1930s",
    "Hand-Painted Anime",
    "Diesel Punk",
    "Pixel Art",
    "God Eater",
    "Classic Oil Paint",
    "Anatomix",
    "Fitness",
    "Dominion",
    "Amateur",
    "Standard 2",
    "Anime Extended",
    "Studio Realistic",
)


def parse_args() -> argparse.Namespace:
    styles_help = "\n".join(f"  {s}" for s in STYLES)
    p = argparse.ArgumentParser(
        description="Continuously generate Flat AI images in visible Chromium.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"Available Flat AI styles:\n{styles_help}",
    )
    p.add_argument("prompt", help="Prompt string for the image generator.")
    p.add_argument("--username", help="Login username/email; overrides config.json.")
    p.add_argument("--password", help="Login password; overrides config.json.")
    p.add_argument("--config", default=DEFAULT_CONFIG,
                    help=f"Credentials JSON file (default: {DEFAULT_CONFIG}).")
    p.add_argument("--aspect-ratio", choices=ASPECT_RATIOS, default="1:1",
                    help="Image aspect ratio (default: 1:1).")
    p.add_argument("--style", choices=STYLES, default="Flat AI Ultra",
                    help='Image style (default: "Flat AI Ultra").')
    p.add_argument("--output-root", default="output",
                    help="Output root directory (default: ./output).")
    p.add_argument("--timeout", type=float, default=180.0,
                    help="Generation/operation timeout in seconds (default: 180).")
    return p.parse_args()


def load_credentials(args: argparse.Namespace) -> tuple[str, str]:
    username, password = args.username, args.password
    if username is None or password is None:
        path = Path(args.config)
        if not path.exists():
            missing = []
            if username is None:
                missing.append("--username")
            if password is None:
                missing.append("--password")
            raise SystemExit(
                f"Missing {', '.join(missing)} and {path} does not exist."
            )
        cfg = json.loads(path.read_text(encoding="utf-8"))
        username = username if username is not None else cfg.get("username")
        password = password if password is not None else cfg.get("password")
    if not username or not password:
        raise SystemExit("Both username and password are required.")
    return username, password


def make_input_parameters(args: argparse.Namespace, username: str) -> dict:
    # Credentials are input to the scraper, but the password is never persisted.
    return {
        "generator": GENERATOR_NAME,
        "generator_url": GENERATOR_URL,
        "prompt": args.prompt,
        "aspect_ratio": args.aspect_ratio,
        "style": args.style,
        "username": username,
    }


def make_output_dir(root: str, params: dict) -> Path:
    canonical = json.dumps(
        params, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
    out = Path(root) / digest
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompt.json").write_text(
        json.dumps(params, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


async def wait_for_element(driver, selectors, timeout: float):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        for by, value in selectors:
            try:
                return await driver.find_element(by, value, timeout=1)
            except Exception as exc:
                last_error = exc
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Element not found: {selectors!r}") from last_error


async def wait_for_elements(driver, by, value, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            elems = await driver.find_elements(by, value)
            if elems:
                return elems
        except Exception:
            pass
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Elements not found: {by}={value}")


async def click_text(driver, text: str, timeout: float, exact: bool = True):
    # XPath literal helper (handles apostrophes in labels).
    def lit(s):
        if "'" not in s:
            return f"'{s}'"
        if '"' not in s:
            return f'"{s}"'
        parts = s.split("'")
        return "concat(" + ", \"'\", ".join(f"'{x}'" for x in parts) + ")"

    t = lit(text)
    if exact:
        xpath = (
            f"//*[normalize-space(text())={t} or @aria-label={t} or @title={t}]"
        )
    else:
        xpath = (
            f"//*[contains(normalize-space(.),{t}) or "
            f"contains(@aria-label,{t}) or contains(@title,{t})]"
        )
    el = await wait_for_element(driver, [(By.XPATH, xpath)], timeout)
    await el.click(move_to=True)
    return el


async def fill(el, value: str):
    try:
        await el.clear()
    except Exception:
        pass
    await el.send_keys(value)


async def login(driver, username: str, password_value: str, timeout: float):
    print("[1] Open login URL")
    await driver.get(LOGIN_URL, wait_load=True, timeout=timeout)

    email = await wait_for_element(
        driver,
        [
            (By.CSS_SELECTOR, 'input[type="email"]'),
            (By.CSS_SELECTOR, 'input[name="email"]'),
            (By.CSS_SELECTOR, 'input[autocomplete="username"]'),
            (By.XPATH, '//input[contains(translate(@placeholder,"EMAIL","email"),"email")]'),
        ],
        timeout,
    )
    pw = await wait_for_element(
        driver,
        [
            (By.CSS_SELECTOR, 'input[type="password"]'),
            (By.CSS_SELECTOR, 'input[name="password"]'),
            (By.CSS_SELECTOR, 'input[autocomplete="current-password"]'),
        ],
        timeout,
    )

    await fill(email, username)
    await fill(pw, password_value)

    print("[2] Enter credentials")
    try:
        await click_text(driver, "Sign in", timeout, exact=True)
    except TimeoutError:
        await click_text(driver, "Sign In", timeout, exact=True)

    # Wait until login redirects away from /login/.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if "/login" not in (await driver.current_url).lower():
                print("[3] Login completed")
                return
        except Exception:
            pass
        await asyncio.sleep(0.5)

    raise TimeoutError("Login did not leave the login page.")


async def select_dropdown_text(driver, label: str, value: str, timeout: float):
    """
    Click a control whose nearby text/aria-label/title identifies it, then
    click the requested option. The generic fallback is useful if the frontend
    changes from <select> to a custom dropdown.
    """
    # Native select first.
    selects = await driver.find_elements(By.CSS_SELECTOR, "select")
    for s in selects:
        try:
            txt = (await s.get_attribute("aria-label")) or ""
            name = (await s.get_attribute("name")) or ""
            if label.lower() in f"{txt} {name}".lower():
                await s.execute_script(
                    "const s=arguments[0],v=arguments[1];"
                    "s.value=v;s.dispatchEvent(new Event('change',{bubbles:true}));",
                    s, value,
                )
                return
        except Exception:
            pass

    # Custom dropdown: locate text/aria-label first.
    candidates = [
        (By.XPATH, f'//*[@aria-label="{label}"]'),
        (By.XPATH, f'//*[@title="{label}"]'),
        (By.XPATH, f'//*[normalize-space(text())="{label}"]'),
        (By.XPATH, f'//*[contains(normalize-space(.),"{label}")]'),
    ]
    control = await wait_for_element(driver, candidates, timeout)
    await control.click(move_to=True)
    await click_text(driver, value, timeout, exact=True)


async def set_aspect_ratio(driver, ratio: str, timeout: float):
    # The Flat AI UI may expose ratio buttons directly.
    try:
        await click_text(driver, ratio, timeout, exact=True)
        print(f"    aspect ratio: {ratio}")
        return
    except TimeoutError:
        pass

    # Try common custom-select containers.
    await select_dropdown_text(driver, "Aspect Ratio", ratio, timeout)
    print(f"    aspect ratio: {ratio}")


async def set_style(driver, style: str, timeout: float):
    # The style gallery is normally directly clickable.
    try:
        await click_text(driver, style, timeout, exact=True)
        print(f"    style: {style}")
        return
    except TimeoutError:
        pass

    await select_dropdown_text(driver, "Style", style, timeout)
    print(f"    style: {style}")


def download_snapshot(download_dir: Path) -> dict[str, float]:
    result = {}
    for p in download_dir.iterdir():
        if p.is_file():
            try:
                result[p.name] = p.stat().st_mtime_ns
            except OSError:
                pass
    return result


async def wait_for_download(
    download_dir: Path, before: dict[str, float], timeout: float
) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = []
        for p in download_dir.iterdir():
            if not p.is_file():
                continue
            if p.name.endswith((".crdownload", ".tmp", ".part")):
                continue
            try:
                mtime = p.stat().st_mtime_ns
            except OSError:
                continue
            if p.name not in before or mtime > before[p.name]:
                candidates.append(p)

        if candidates:
            # A download is complete once Chrome's temporary .crdownload file
            # has disappeared and the file has stopped changing.
            candidates.sort(key=lambda x: x.stat().st_mtime_ns, reverse=True)
            candidate = candidates[0]
            size1 = candidate.stat().st_size
            await asyncio.sleep(0.4)
            if candidate.exists() and candidate.stat().st_size == size1:
                return candidate

        await asyncio.sleep(0.25)

    raise TimeoutError(f"No completed browser download appeared in {download_dir}")


def seed_from_filename(name: str) -> str | None:
    m = re.search(r"seed-(\d+)", name, flags=re.I)
    return m.group(1) if m else None


def unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        candidate = path.with_name(f"{stem}.{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def move_non_upscaled(downloaded: Path, output_dir: Path, seed: str) -> Path:
    suffix = downloaded.suffix.lower() or ".jpg"
    target = unique_target(output_dir / f"{seed}{suffix}")
    shutil.move(str(downloaded), str(target))
    return target


def move_upscaled(downloaded: Path, output_dir: Path, seed: str) -> Path:
    suffix = downloaded.suffix.lower() or ".jpg"
    target = unique_target(output_dir / f"{seed}.upscaled{suffix}")
    shutil.move(str(downloaded), str(target))
    return target


def add_exif(path: Path, params: dict):
    """
    EXIF has no universally-defined fields for every application-specific
    input. We therefore store the complete JSON in EXIF UserComment and also
    expose the prompt/generator in standard EXIF fields where possible.
    """
    params_json = json.dumps(params, ensure_ascii=False, sort_keys=True)

    try:
        exif = piexif.load(str(path))
    except Exception:
        exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    zeroth = exif.setdefault("0th", {})
    exif_ifd = exif.setdefault("Exif", {})

    zeroth[piexif.ImageIFD.ImageDescription] = params["prompt"].encode("utf-8")
    zeroth[piexif.ImageIFD.Software] = GENERATOR_NAME.encode("utf-8")
    # EXIF UserComment: ASCII prefix followed by UTF-8 JSON.
    exif_ifd[piexif.ExifIFD.UserComment] = b"UNICODE\0" + params_json.encode("utf-8")

    # Also preserve a compact JSON copy in XPComment when supported by viewers.
    try:
        zeroth[piexif.ImageIFD.XPComment] = params_json.encode("utf-16le") + b"\x00\x00"
    except Exception:
        pass

    exif_bytes = piexif.dump(exif)

    # Preserve image data/format while replacing EXIF.
    with Image.open(path) as im:
        if "exif" in im.info:
            im.save(path, exif=exif_bytes)
        else:
            im.save(path, exif=exif_bytes)


async def wait_for_generated_image(driver, timeout: float):
    """
    Wait until an image link matching /ai-image/<token>/ exists. This mirrors
    the HTTP traffic in the supplied HAR, where generation polling eventually
    returns such a URL.
    """
    deadline = time.monotonic() + timeout
    xpath = '//img[contains(@src,"/ai-image/")] | //a[contains(@href,"/ai-image/")]'
    while time.monotonic() < deadline:
        try:
            elems = await driver.find_elements(By.XPATH, xpath)
            for el in elems:
                try:
                    src = await el.get_attribute("src")
                    href = await el.get_attribute("href")
                    if (src and "/ai-image/" in src) or (href and "/ai-image/" in href):
                        return
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise TimeoutError("Generated image did not appear before timeout.")


async def wait_for_generate_button(driver, timeout: float):
    return await wait_for_element(
        driver,
        [
            (By.XPATH, '//*[normalize-space(text())="Generate"]'),
            (By.CSS_SELECTOR, 'button[type="submit"]'),
            (By.CSS_SELECTOR, 'button'),
        ],
        timeout,
    )


async def click_download(driver, timeout: float):
    # User-visible tooltip/title is "Download Image" according to the HAR/UI.
    selectors = [
        (By.XPATH, '//*[@title="Download Image"]'),
        (By.XPATH, '//*[@aria-label="Download Image"]'),
        (By.XPATH, '//*[normalize-space(text())="Download"]'),
        (By.XPATH, '//button[contains(@title,"Download")]'),
        (By.XPATH, '//a[contains(@download,"flatai")]'),
    ]
    el = await wait_for_element(driver, selectors, timeout)
    await el.click(move_to=True)


async def upscale_current_image(driver, timeout: float):
    print("[13] Open Tools menu")
    try:
        await click_text(driver, "Tools", timeout, exact=True)
    except TimeoutError:
        await click_text(driver, "Tools", timeout, exact=False)

    print("[14] Click Upscale")
    await click_text(driver, "Upscale", timeout, exact=True)


async def one_generation(
    driver,
    args,
    output_dir: Path,
    params: dict,
    download_dir: Path,
    iteration: int,
):
    print(f"\n=== Generation {iteration} ===")

    # 5. Prompt
    prompt_box = await wait_for_element(
        driver,
        [
            (By.CSS_SELECTOR, "textarea"),
            (By.XPATH, '//textarea[contains(@placeholder,"Your prompt")]'),
            (By.XPATH, '//textarea[contains(@aria-label,"Your prompt")]'),
        ],
        args.timeout,
    )
    await fill(prompt_box, args.prompt)

    # 6–7. Ratio and style.
    await set_aspect_ratio(driver, args.aspect_ratio, args.timeout)
    await set_style(driver, args.style, args.timeout)

    # 8. Generate.
    print("[8] Click Generate")
    before_download = download_snapshot(download_dir)
    generate = await wait_for_generate_button(driver, args.timeout)
    await generate.click(move_to=True)

    # 9. Wait.
    print("[9] Waiting for generated image...")
    await wait_for_generated_image(driver, args.timeout)

    # 10–11. Download non-upscaled image.
    print("[10] Click Download")
    await click_download(driver, args.timeout)
    print("[11] Waiting for download...")
    downloaded = await wait_for_download(download_dir, before_download, args.timeout)

    # The site names generated downloads like:
    # flatai-generated-image-seed-721845929.jpg
    seed = seed_from_filename(downloaded.name)
    if seed is None:
        # Fallback: the generation response exposes the seed in the UI/DOM in
        # current versions; if the filename changes, use a timestamp-safe ID.
        seed = str(int(time.time() * 1000))
        print(f"Warning: no seed in filename {downloaded.name!r}; using {seed}")

    non_upscaled = move_non_upscaled(downloaded, output_dir, seed)
    print(f"[12] Saved {non_upscaled}")

    # 13–18. Upscale is a separate Flat AI job.
    before_upscale_download = download_snapshot(download_dir)
    await upscale_current_image(driver, args.timeout)

    print("[15] Waiting for upscale generation...")
    await wait_for_generated_image(driver, args.timeout)

    print("[16] Click Download")
    await click_download(driver, args.timeout)

    print("[17] Waiting for upscale download...")
    upscaled_download = await wait_for_download(
        download_dir, before_upscale_download, args.timeout
    )
    upscaled = move_upscaled(upscaled_download, output_dir, seed)
    print(f"[18] Saved {upscaled}")

    # Add the same input metadata to both files.
    add_exif(non_upscaled, params)
    add_exif(upscaled, params)
    print("    EXIF metadata written")


async def main_async():
    args = parse_args()
    username, password = load_credentials(args)

    params = make_input_parameters(args, username)
    output_dir = make_output_dir(args.output_root, params)

    # A private download directory prevents unrelated Chrome downloads from
    # being mistaken for generated images.
    download_dir = output_dir / ".downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    print(f"Output directory: {output_dir}")
    print(f"prompt.json:      {output_dir / 'prompt.json'}")
    print(f"Aspect ratio:     {args.aspect_ratio}")
    print(f"Style:            {args.style}")

    options = webdriver.ChromeOptions()

    # Headful is the default: do NOT add --headless.
    options.add_argument("--start-maximized")
    options.update_pref("download.prompt_for_download", False)
    options.update_pref("download.directory_upgrade", True)
    options.update_pref("download.default_directory", str(download_dir.resolve()))
    options.update_pref("safebrowsing.enabled", True)

    # Allow repeated automatic downloads.
    options.update_pref("profile.default_content_setting_values.automatic_downloads", 1)

    print("Starting visible Chromium...")
    async with webdriver.Chrome(options=options) as driver:
        await login(driver, username, password, args.timeout)

        print("[4] Open Image Studio")
        await driver.get(GENERATOR_URL, wait_load=True, timeout=args.timeout)

        # Let the SPA finish rendering.
        await asyncio.sleep(2)

        iteration = 1
        while True:
            try:
                await one_generation(
                    driver,
                    args,
                    output_dir,
                    params,
                    download_dir,
                    iteration,
                )
                iteration += 1

                # Step 19: repeat from Generate. The prompt/ratio/style remain
                # selected, so the next iteration begins with Generate.
                await asyncio.sleep(0.5)

            except KeyboardInterrupt:
                print("\nStopping.")
                break
            except Exception as exc:
                print(f"\nGeneration {iteration} failed: {exc!r}", file=sys.stderr)
                print("The browser remains open. Retrying after 5 seconds...", file=sys.stderr)
                await asyncio.sleep(5)


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
