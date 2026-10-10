#!/bin/zsh
# Record and cut the demo video.
#   ./run.sh <dir holding home-server-demo.mp4 and its .trimscript.json> <out dir>
# Needs: Google Chrome, `npm i playwright`, `brew install vhs`, Claude Code logged in.
set -e
here=${0:A:h}
A=${1:A}; OUT=${2:A}
TRIMSCRIPT=${TRIMSCRIPT:-$here/../../.venv/bin/trimscript}
cp $here/agent.tape $A/agent.tape
cat > $A/mcp.json <<JSON
{"mcpServers": {"trimscript": {"command": "$TRIMSCRIPT", "args": ["mcp"]}}}
JSON
pkill -f "trimscript open home-server-demo.mp4 --port 4750" || true
sleep 1
python3 -c "
import json, sys; p = sys.argv[1]; d = json.load(open(p)); d['cuts'] = []; d['settings'] = {}; json.dump(d, open(p, 'w'))
" $A/home-server-demo.mp4.trimscript.json
(cd $A && nohup $TRIMSCRIPT open home-server-demo.mp4 --port 4750 --no-browser > server.log 2>&1 &)
sleep 4
node $here/record.mjs http://127.0.0.1:4750/ $OUT/take $A
result=$(cd $A && $TRIMSCRIPT show home-server-demo.mp4 | head -1 | sed -E 's/.*  //')
node $here/cards.mjs $OUT/cards "$result"
python3 $here/compose.py $OUT/take $A/agent.mp4 $OUT/cards $OUT/demo.mp4
