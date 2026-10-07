import argparse
import sys

from serialterminal import __version__, path_setup


def main(argv=None):
    """Console-script entry point (see pyproject [project.scripts])."""
    parser = argparse.ArgumentParser(
        prog="serialterminal",
        description="Textual TUI for talking to serial devices.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--add-to-path",
        action="store_true",
        help="put the folder holding the serialterminal command on your user "
             "PATH (Windows; prints the shell line elsewhere) and exit",
    )
    args = parser.parse_args(argv)

    if args.add_to_path:
        return path_setup.add_to_path_command()

    # Imported here so --add-to-path and --help don't pay for loading Textual.
    from serialterminal.ui.app import TUIApp

    path_setup.offer_on_first_launch()
    TUIApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
