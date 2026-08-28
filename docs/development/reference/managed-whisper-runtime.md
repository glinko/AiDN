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

## Approved Runtime path

The standard Provider workflow creates a `whisper-http` Runtime Binding and
uses the RFC-0054 Approved Runtime Dispatcher. The binding carries the selected
`api_format` (`whisper_asr_webservice` by default) and the
`whisper-http.v1` Usage Profile. Fixed-price requests therefore remain valid
when Whisper does not expose token or audio-duration measurements; the final
Usage Report records those dimensions as `UNAVAILABLE` rather than inventing
zeros.

The dashboard selects the provider's `whisper-local-http` recipe automatically.
An already successful approval is displayed as `Already Applied` and cannot be
submitted again unless its job is rolled back.

## Request audio transport

For the native `whisper_asr_webservice` adapter, `audio_ref` is a restricted
inline data URI, for example:

```text
data:audio/wav;base64,<base64-audio>
```

The adapter accepts common audio MIME types and limits inline payloads to 25 MiB.
It never opens an arbitrary filesystem path from a Request. The adapter converts
the bytes to the native `/asr?task=transcribe&output=json` multipart contract using the
`audio_file` field. A future artifact store can replace the inline transport
without changing the provider boundary.
