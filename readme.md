# Ren'Py Video Compressor

This short and sweet utility was written to automate conversion of 60-fps, high-quality videos to lower-rate, lower-quality videos for compressed versions of my Ren'Py game releases. But it could be ostensibly used for any task requiring mass-conversion of videos. It handles `.MKV`, `.MP4`, and `.WEBM` formats out of the box. Others can be added as limited by `ffmpeg`.

It uses `PyQt5` for the app shell and process handling, and `ffmpeg/ffprobe` for the conversion process. It will utilize NVIDIA card CUDA cores if they exist (and you so specify.) It uses a `QThreadPool` of 4 entries, which seems to work optimally for me, but can be changed in the __init__() method of the `VideoCompressorApp` class.

Whatever compression ratio you choose calculates the output files' bitrate as a percentage of the original. So if videos are already at a lower bitrate, the compression ratio will need to be higher to account. For me, 60-fps high-bitrate videos compress well to 24-fps videos at 30% quality, but YMMV.

Also included is the `.spec` file needed for PyInstaller to build a one-file executable for Windows. It should work with minimal alterations for other platforms.
