# Ampul — Desktop Widget for Fonri / Tuya Smart Bulbs

A small always-on-top **Windows desktop widget** to control a Fonri (Tuya) smart bulb: on/off, brightness, white temperature and colors — without opening the phone app.

*Fonri / Tuya akıllı ampulü masaüstünden kontrol eden küçük pencere.*

## Features

- Round power button that shows the bulb's current color
- **White** tab (warm ↔ cool, brightness) and **Color** tab (hue wheel, saturation, brightness, quick swatches)
- Commands go over the **local network first** (fast); if that fails they go through the Tuya cloud
- Status dot: green = local network, yellow = cloud
- Minimize to the taskbar, drag from the title bar, right-click menu (always on top, reconnect, choose device, QR login)
- If no Tuya IoT keys are set, it falls back to **Smart Life QR login**

## Setup

1. Create a cloud project at [iot.tuya.com](https://iot.tuya.com) and link your Smart Life account to it.
2. Copy `.env.example` to `.env` and fill in your own **Access ID** and **Access Secret**:
   ```
   TUYA_API_KEY=your_access_id
   TUYA_API_SECRET=your_access_secret
   TUYA_API_REGION=eu
   ```
   Put `.env` next to `ampul_widget.py` (or next to `Ampul.exe`, or in `%APPDATA%\AmpulWidget`).
   **Never commit `.env`** — it is in `.gitignore`.
3. Run it:
   ```bash
   pip install tinytuya tuya-device-sharing-sdk qrcode
   pythonw ampul_widget.py
   ```
   Or double-click **`kur.bat`** to build `Ampul.exe` with PyInstaller and add desktop / Start menu shortcuts (see `OKU_BENI.txt`, Turkish).

Device ID and local key are fetched from the Tuya cloud and stored in `%APPDATA%\AmpulWidget\ampul_config.json` on your PC.

## Note

Tuya bulbs only use **2.4 GHz** Wi-Fi.

## License

MIT — see [LICENSE](LICENSE).
