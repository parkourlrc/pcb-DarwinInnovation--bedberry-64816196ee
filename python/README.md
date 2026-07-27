# Bedberry Python Core

Initial asyncio-based Python reimplementation of the Bedberry hardware core.

## Stack
- `smbus2` for Linux I2C access
- `rpi-lgpio` (`RPi.GPIO` compatible import) for GPIO interrupts
- `asyncio` for command/state/timer orchestration

## Run
1. Install OS prerequisites (Debian/Raspberry Pi OS):

```bash
sudo apt-get update
sudo apt-get install -y swig build-essential python3-dev liblgpio-dev liblgpio1
```

2. Create and activate a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
```

3. Install Python dependencies:

```bash
pip install -r requirements.txt
```

4. Launch using existing config files from the Node implementation:

```bash
python -m bedberry.main --config-dir ../software/cfg
```

Enable verbose debug logging:

```bash
python -m bedberry.main --config-dir ../software/cfg --verbose
```

Default bus is `--i2c-bus 1`.

If bus 1 does not exist on your platform, pass the detected bus explicitly:

```bash
ls -l /dev/i2c-*
python -m bedberry.main --config-dir ../software/cfg --i2c-bus 20
```

Use Ctrl+C to stop.

## Run As A Systemd Service

Service file in this repo:

```bash
/home/pi/bedberry/python/bedberry-python.service
```

Install and enable at boot:

```bash
sudo cp /home/pi/bedberry/python/bedberry-python.service /etc/systemd/system/bedberry-python.service
sudo systemctl daemon-reload
sudo systemctl enable --now bedberry-python.service
```

Check status:

```bash
systemctl status bedberry-python.service --no-pager -l
systemctl is-enabled bedberry-python.service
systemctl is-active bedberry-python.service
```

View logs:

```bash
journalctl -u bedberry-python.service -f
journalctl -u bedberry-python.service -n 100 --no-pager
```

Restart after config/code changes:

```bash
sudo systemctl restart bedberry-python.service
```

Disable service (stop autostart on boot):

```bash
sudo systemctl disable --now bedberry-python.service
```
