import os
from flask import Flask, render_template_string

app = Flask(__name__)

HTML_PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Goaltech Chess</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1e1e24;
            color: #f7f7f8;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
        }
        h1 { margin-bottom: 8px; color: #4ade80; }
        p { margin-top: 0; color: #a1a1aa; font-size: 15px; }
        #status { font-weight: 600; margin-bottom: 12px; font-size: 18px; }
        .board {
            display: grid;
            grid-template-columns: repeat(8, 60px);
            grid-template-rows: repeat(8, 60px);
            border: 4px solid #3f3f46;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        }
        @media (max-width: 520px) {
            .board {
                grid-template-columns: repeat(8, 42px);
                grid-template-rows: repeat(8, 42px);
            }
            .square { font-size: 26px !important; }
        }
        .square {
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 38px;
            cursor: pointer;
            user-select: none;
            transition: background 0.15s;
        }
        .light { background-color: #e2d6b5; color: #222; }
        .dark { background-color: #b88b4a; color: #222; }
        .selected { background-color: #86efac !important; }
        .reset-btn {
            margin-top: 20px;
            padding: 10px 20px;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 15px;
            font-weight: bold;
            cursor: pointer;
        }
        .reset-btn:hover { background: #1d4ed8; }
    </style>
</head>
<body>
    <h1>Goaltech Chess</h1>
    <p>Taşlara tıklayarak oyna (2 Kişilik / Sırayla)</p>
    <div id="status">Sıra: Beyaz</div>
    <div class="board" id="board"></div>
    <button class="reset-btn" onclick="resetBoard()">Yeni Oyun</button>

    <script>
        const initialBoard = [
            ['♜','♞','♝','♛','♚','♝','♞','♜'],
            ['♟','♟','♟','♟','♟','♟','♟','♟'],
            ['','','','','','','',''],
            ['','','','','','','',''],
            ['','','','','','','',''],
            ['','','','','','','',''],
            ['♙','♙','♙','♙','♙','♙','♙','♙'],
            ['♖','♘','♗','♕','♔','♗','♘','♖']
        ];

        let board = JSON.parse(JSON.stringify(initialBoard));
        let selectedSquare = null;
        let turn = 'Beyaz';

        const whitePieces = ['♙','♖','♘','♗','♕','♔'];
        const blackPieces = ['♟','♜','♞','♝','♛','♚'];

        function isPieceOfTurn(piece, currentTurn) {
            if (currentTurn === 'Beyaz') return whitePieces.includes(piece);
            return blackPieces.includes(piece);
        }

        function render() {
            const boardEl = document.getElementById('board');
            boardEl.innerHTML = '';
            for (let r = 0; r < 8; r++) {
                for (let c = 0; c < 8; c++) {
                    const sq = document.createElement('div');
                    sq.className = 'square ' + ((r + c) % 2 === 0 ? 'light' : 'dark');
                    sq.innerText = board[r][c];

                    if (selectedSquare && selectedSquare.r === r && selectedSquare.c === c) {
                        sq.classList.add('selected');
                    }

                    sq.onclick = () => handleSquareClick(r, c);
                    boardEl.appendChild(sq);
                }
            }
            document.getElementById('status').innerText = 'Sıra: ' + turn;
        }

        function handleSquareClick(r, c) {
            const clickedPiece = board[r][c];

            if (selectedSquare) {
                if (selectedSquare.r === r && selectedSquare.c === c) {
                    selectedSquare = null;
                    render();
                    return;
                }

                if (isPieceOfTurn(clickedPiece, turn)) {
                    selectedSquare = { r, c };
                    render();
                    return;
                }

                board[r][c] = board[selectedSquare.r][selectedSquare.c];
                board[selectedSquare.r][selectedSquare.c] = '';
                selectedSquare = null;
                turn = turn === 'Beyaz' ? 'Siyah' : 'Beyaz';
                render();
            } else {
                if (clickedPiece && isPieceOfTurn(clickedPiece, turn)) {
                    selectedSquare = { r, c };
                    render();
                }
            }
        }

        function resetBoard() {
            board = JSON.parse(JSON.stringify(initialBoard));
            selectedSquare = null;
            turn = 'Beyaz';
            render();
        }

        render();
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_PAGE)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
