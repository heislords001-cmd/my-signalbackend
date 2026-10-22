# FX Desk scanner (backend, runs on your VPS: Windows or Linux)

Do this AFTER the database (supabase-setup.sql) and the website are set up.

## What is here
- `worker.py`: the SCANNER. It watches the market and sends signals to the website. It only reads prices and never trades.
- `test_*.py`: checks that the code works.
- `bot.py`, `engine.py`, `broker.py`: the trading bot. It needs MT5, so it runs on a Windows PC, not on this VPS. Members and you get it from the website (Profile > Bot access).

## Setup on a WINDOWS VPS (no MT5 needed to start)
1. Install Python 3.11 or newer from python.org. On the first screen, tick "Add python.exe to PATH".
2. Copy `fx-desk-backend.zip` to the VPS (copy and paste works through Remote Desktop). Right-click it, Extract All, for example into `C:\fxdesk`.
3. Open the `fx-desk-backend` folder, click the address bar at the top, type `cmd` and press Enter. A black window opens in that folder.
4. In the black window run: `pip install -r requirements.txt`
5. Make a copy of `.env.example` and name it `.env`. Open it with Notepad and fill in `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`. Leave `FEED=yahoo`.
6. In the black window run: `python test_scanner.py` (it should end with "all scanner tests passed").
7. Double-click `start-scanner.bat`. A window opens and keeps the scanner running. Leave it open.
8. On the website: Home > Start scanner. The first start backtests everything and takes a few minutes.

### Keeping it running
- When you leave the VPS, close Remote Desktop with the X at the top (Disconnect). Never choose Sign out or Shut down, because that stops the scanner.
- To start it by itself after a reboot: open Task Scheduler > Create Basic Task > trigger "When the computer starts" > action "Start a program" > pick `start-scanner.bat`. Tick "Run whether user is logged on or not".

## Setup on a LINUX VPS (copy and paste these in your terminal, one block at a time)
Upload `fx-desk-backend.zip` to the VPS first (WinSCP, or the SFTP tab in Termius), into `/opt/fxdesk`. Then:

    sudo apt update && sudo apt install -y python3-venv unzip
    cd /opt/fxdesk && unzip -o fx-desk-backend.zip
    cd fx-desk-backend
    python3 -m venv venv
    venv/bin/pip install -r requirements.txt

Create your settings file and fill it in (nano: arrows to move, Ctrl+O then Enter to save, Ctrl+X to exit):

    cp .env.example .env
    nano .env

Check everything works (it should end with "all scanner tests passed"):

    venv/bin/python test_scanner.py

Start it as a service that keeps running when you close the terminal, and restarts itself after a reboot:

    sudo cp fx-scanner.service /etc/systemd/system/
    sudo systemctl enable --now fx-scanner

Watch it run (Ctrl+C stops watching, NOT the scanner):

    sudo journalctl -u fx-scanner -f

Then on the website: Home > Start scanner. The first start backtests everything and takes a few minutes.

## Good to know
- The service key in `.env` is secret. It only lives on your VPS.
- Prices come from Yahoo Finance (free). They are close to your broker's, but not identical, so treat entries as approximate and use the distances to the stop and targets.
- Yahoo only gives about 2 months of 5-minute and 15-minute history and 2 years of 1-hour history. So fewer combinations pass the test at first, mostly 1-hour ones. That is the safety check being strict, not a fault.
- To update: upload the new zip, run `unzip -o`, then `sudo systemctl restart fx-scanner`.
