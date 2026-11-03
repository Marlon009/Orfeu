#!/usr/bin/env bash
# Regera as conversas de exemplo a partir dos roteiros (leva vários minutos em CPU).
# Uso: ./examples/gerar.sh [pasta_de_saida]   (modelo e modo vêm de LLM_MODEL e EMPORIO_MODE)
set -e
cd "$(dirname "$0")/.."
OUT="${1:-examples}"
mkdir -p "$OUT"
# Começa cada exemplo do zero (sem histórico de rodadas anteriores).
python3 -c "from emporio.db import connect; c = connect(); c.execute(\"DELETE FROM messages WHERE session_id LIKE 'ex0%'\"); c.execute('DELETE FROM complaints'); c.commit()"
run() { python3 -m emporio.cli --roteiro "examples/roteiros/$1.txt" --saida "$OUT/$1.md" "${@:2}"; }
run 01_catalogo_violoes --sessao ex01
run 02_loja_e_fora_de_escopo --sessao ex02
run 03_devolucao_pedido --sessao ex03
run 04_cliente_identificado_atraso --telefone "(67) 99654-7821" --sessao ex04
run 05_produto_esgotado --sessao ex05
