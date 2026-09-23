#!/usr/bin/env bash
# Собирает PDF из HTML-исходников продающих документов.
# Использование:  ./docs/sales/build.sh        (из корня репозитория)
set -euo pipefail

cd "$(dirname "$0")/../.."

command -v weasyprint >/dev/null || { echo "weasyprint не найден: pip install weasyprint"; exit 1; }

weasyprint docs/sales/01-sotuv-qollanmasi.html FleetWatch-Sotuv-Qollanmasi.pdf
weasyprint docs/sales/02-taklif-varaqasi.html  FleetWatch-Taklif-Varaqasi.pdf
weasyprint docs/sales/03-pilot-kelishuvi.html  FleetWatch-Pilot-Kelishuvi.pdf

echo "Готово:"
ls -lh FleetWatch-*.pdf
