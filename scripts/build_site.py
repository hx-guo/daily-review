from pathlib import Path

from gdr.site_build import build_site


ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    out_dir = build_site(ROOT)
    n_files = sum(1 for path in out_dir.rglob("*") if path.is_file())
    print(f"built {n_files} static files in {out_dir}")


if __name__ == "__main__":
    main()
