# Managed Whisper Runtime

`tools/aidn-whisper-runtime-ubuntu.sh` starts the first real Provider runtime
used by the MVP. It is deliberately narrower than the Provider Plugin API:

* only the reviewed `onerahmet/openai-whisper-asr-webservice:v1.9.1` image;
* only models `tiny`, `base`, `small`, `medium`, and `large-v3`;
* only `127.0.0.1:9000`, never a LAN-exposed inference port;
* persistent files only below `/var/lib/aidn/whisper`;
* Docker resource and privilege limits are fixed by the script.

Run it on an Ubuntu operator host after Docker is installed:

```bash
sudo bash tools/aidn-whisper-runtime-ubuntu.sh start --model base
sudo bash tools/aidn-whisper-runtime-ubuntu.sh status
```

The first start downloads the approved image and selected Whisper model. The
Hypervisor's Whisper Provider should use `http://127.0.0.1:9000` as its endpoint.
The current installer is an operator-owned runtime boundary. A later host
controller will make the same bounded operation callable from an approved
dashboard plan without granting the Hypervisor Docker access.
