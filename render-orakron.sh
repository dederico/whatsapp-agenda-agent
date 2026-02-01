#!/bin/bash
# Script de ayuda para usar Render CLI con la cuenta de Orakron

export RENDER_CLI_CONFIG_PATH=~/.render/cli-orakron.yaml

echo "✅ Usando cuenta: developer@beholder.com.mx (Orakron)"
echo ""

# Si se pasan argumentos, ejecutar el comando render con esos argumentos
if [ $# -gt 0 ]; then
    render "$@"
else
    echo "Uso: ./render-orakron.sh [comando de render]"
    echo ""
    echo "Ejemplos:"
    echo "  ./render-orakron.sh services list -o yaml"
    echo "  ./render-orakron.sh logs srv-d5r9prm3jp1c73fio0g0"
    echo "  ./render-orakron.sh whoami"
    echo ""
    echo "Servicios disponibles:"
    echo "  - Backend:  srv-d5r9prm3jp1c73fio0g0 (Agente-Agenda-Calendario-Api)"
    echo "  - Gateway:  srv-d5r9prm3jp1c73fio0b0 (Agente-Agenda-Calendario)"
    echo "  - Database: dpg-d5r99kv5r7bs7392jovg-a (agente-personal-agenda-calendario)"
fi
