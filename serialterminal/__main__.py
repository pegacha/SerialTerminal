import argparse
import subprocess
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
    app = TUIApp()
    app.run()

    # "Update and restart" in the update dialog: pip runs now, with the app
    # closed and its output in this console, then the new version starts.
    target = getattr(app, "update_target", None)
    if target:
        from serialterminal import updater
        if updater.launched_by_exe():
            updater.install_after_exit(target)
            print("SerialTerminal is updating in a new window and will start again there.")
            return 0
        code = updater.install(target)
        if code != 0:
            print("The update failed; SerialTerminal is unchanged. To retry by hand:\n"
                  f"  {sys.executable} -m pip install --upgrade {target}")
            return code
        print("Updated. Starting SerialTerminal...", flush=True)
        return subprocess.call([sys.executable, "-m", "serialterminal", *(argv or [])])
    return 0


if __name__ == "__main__":
    sys.exit(main())
