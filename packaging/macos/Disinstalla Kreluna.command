#!/bin/bash
set -euo pipefail

APP="/Applications/Kreluna Director.app"
SUPPORT="$HOME/Library/Application Support/KrelunaDirector"
CACHE="$HOME/Library/Caches/studio.kreluna.director"
PREFS="$HOME/Library/Preferences/studio.kreluna.director.plist"
STATE="$HOME/Library/Saved Application State/studio.kreluna.director.savedState"

ANSWER="$(/usr/bin/osascript -e 'button returned of (display dialog "Vuoi spostare nel Cestino Kreluna Director e tutti i suoi dati locali? Verranno rimossi database, documenti, accessi cifrati, configurazione IA e preferenze. Gli Agent installati sugli altri computer non verranno cancellati." buttons {"Annulla", "Sposta tutto nel Cestino"} default button "Annulla" with icon caution with title "Disinstalla Kreluna")')"
if [[ "$ANSWER" != "Sposta tutto nel Cestino" ]]; then
  exit 0
fi

/usr/bin/pkill -f '/Kreluna Director.app/Contents/MacOS/Kreluna' >/dev/null 2>&1 || true
/bin/sleep 1

trash_item() {
  local target="$1"
  [[ -e "$target" ]] || return 0
  /usr/bin/osascript - "$target" <<'APPLESCRIPT'
on run argv
  tell application "Finder"
    delete POSIX file (item 1 of argv)
  end tell
end run
APPLESCRIPT
}

trash_item "$SUPPORT"
trash_item "$CACHE"
trash_item "$PREFS"
trash_item "$STATE"
trash_item "$APP"

/usr/bin/osascript -e 'display dialog "Kreluna Director e tutti i dati locali sono stati spostati nel Cestino. Per eliminarli definitivamente, svuota il Cestino." buttons {"OK"} default button "OK" with title "Kreluna disinstallata"'
