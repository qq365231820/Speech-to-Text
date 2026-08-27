import multiprocessing
import sys

def main():
    if sys.platform != "win32":
        raise SystemExit("This application supports Windows only.")
    from voiceinput.app import run
    run()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
