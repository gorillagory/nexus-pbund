import argparse, threading, time, os
from engine import NexusEngine, NexusWatcher
from dashboard import NexusDashboard
from watchdog.observers import Observer

def main():
    parser = argparse.ArgumentParser(description="Nexus OS")
    parser.add_argument('command', choices=['watch', 'super'])
    parser.add_argument('--dir', default='..')
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()

    engine = NexusEngine(os.path.abspath(args.dir))
    engine.run_analysis()

    if args.command == 'watch':
        threading.Thread(target=NexusDashboard(engine).run, args=(args.port,), daemon=True).start()
        observer = Observer()
        observer.schedule(NexusWatcher(engine), engine.target_dir, recursive=True)
        observer.start()
        print(f"[*] NEXUS OS ACTIVE: [http://127.0.0.1](http://127.0.0.1):{args.port}")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

if __name__ == "__main__":
    main()
