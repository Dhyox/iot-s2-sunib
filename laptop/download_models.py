"""Unduh model YuNet (deteksi) dan SFace (recognition) dari OpenCV Zoo."""
import urllib.request

from config import DETECTOR_MODEL, MODEL_DIR, RECOGNIZER_MODEL

URLS = {
    DETECTOR_MODEL: "https://github.com/opencv/opencv_zoo/raw/main/models/"
                    "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    RECOGNIZER_MODEL: "https://github.com/opencv/opencv_zoo/raw/main/models/"
                      "face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def main():
    MODEL_DIR.mkdir(exist_ok=True)
    for path, url in URLS.items():
        if path.exists() and path.stat().st_size > 10_000:
            print(f"Sudah ada: {path.name}")
            continue
        print(f"Mengunduh {path.name} ...")
        urllib.request.urlretrieve(url, path)
        size_kb = path.stat().st_size // 1024
        if size_kb < 10:
            raise SystemExit(f"Unduhan {path.name} gagal (file terlalu kecil). "
                             f"Unduh manual dari: {url}")
        print(f"  selesai ({size_kb} KB)")


if __name__ == "__main__":
    main()
