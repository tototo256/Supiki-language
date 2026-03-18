import sys
import re
import os


# -------------------------------------------------------
# エラークラス
# -------------------------------------------------------

class SpikiError(Exception):
    """Spiki実行時エラーの基底クラス"""
    pass


class SpikiCompileError(SpikiError):
    """
    コンパイル時エラー。
    ソースの行・列・トークン文字列・行テキストを保持し、
    整形されたエラーメッセージを生成する。
    """
    def __init__(self, message: str, line: int, col: int, token: str, line_text: str):
        self.line = line
        self.col = col
        self.token = token
        self.line_text = line_text
        super().__init__(message)

    def format(self) -> str:
        """
        例:
          コンパイルエラー: 対応する '[' のない ']' があります
           --> 3行目, 5文字目
            3 | ﾁｮﾜﾖｰ! ｽﾋﾟｷ! ﾁｮﾜﾖｰ!
                        ^^^^^^^
        """
        arrow = " --> "
        lines = [
            f"コンパイルエラー: {self.args[0]}",
            f"{arrow}{self.line}行目, {self.col}文字目",
            f"{self.line:>4} | {self.line_text}",
            f"       {' ' * (self.col - 1)}{'^' * len(self.token)}",
        ]
        return "\n".join(lines)


class SpikiInterpreter:
    CELL_SIZE = 30000

    def __init__(self, code: str):
        self.original_code = code

        # コメント除去（オフセットマッピング付き）
        self.clean_code, self.offset_map = self._remove_comments(code)

        self.commands = {
            "ｱ!":                                                    "+",
            "ｳﾜｧｧ!":                                                 "-",
            "ｽﾋﾟｷ!":                                                 ">",
            "ｽﾋﾟｷﾃﾞﾙｼﾞﾊﾞｾﾞﾖ!":                                     "<",
            "ｽﾋﾟｷﾓﾘﾁｬﾊﾞﾀﾞﾝｷﾞｼﾞﾊﾞｾﾞﾖ!":                             ".",
            "ｽﾋﾟｷｦｲｼﾞﾒﾇﾝﾃﾞ":                                        ",",
            "ﾁｮﾜﾖｰﾁｮﾜﾖｰﾑﾙｺﾞﾜﾚｯｼﾞﾁｮﾜﾖｰ": "L",
            "ﾁｮﾜﾖｰ":                                                 "[",
            "ﾁｮﾜﾖｰ!":                                               "]",
            "ﾁｮﾜﾖｰﾁｮﾜﾖｰﾎﾊﾞｷﾞﾁｮﾜﾖｰ":                               "z",
            "ﾁｮﾜﾖｰﾁｮﾜﾖｰｿﾝﾊﾞｺｯﾁﾁｮﾜﾖｰ":                             "i",
            "ﾃﾞﾙｼﾞﾊﾞｾﾞﾖ!":                                         "q",
            "ﾈﾙﾇｲﾛｯﾀﾞｲﾛｯｹﾎﾟﾝﾆｮｸﾁｮｷﾞﾖｯｶﾘｱﾆﾗﾝﾏﾙｲｴﾖ!":               "p",
        }

        # (token_str, clean_code上のオフセット) のリスト
        self.tokens, self.token_offsets = self._tokenize()
        self.bracket_map = self._build_bracket_map()

    # -------------------------------------------------------
    # コメント除去（オフセットマッピング付き）
    # offset_map[clean_index] = original_index
    # -------------------------------------------------------
    def _remove_comments(self, code: str) -> tuple[str, list[int]]:
        # ｱｰｳ ... ｱｰｳ をコメントとして除去する。
        # 同じマーカーが開始・終了を兼ねるため、
        # depth==0 なら開始（depth+1）、depth>0 なら終了（depth-1）とする。
        MARKER = "ｱｰｳ"
        mlen = len(MARKER)
        result = []
        offset_map = []
        i = 0
        depth = 0
        while i < len(code):
            if code[i:i + mlen] == MARKER:
                if depth == 0:
                    depth += 1   # コメント開始
                else:
                    depth -= 1   # コメント終了
                i += mlen
            elif depth > 0:
                i += 1           # コメント内: 読み飛ばす
            else:
                offset_map.append(i)
                result.append(code[i])
                i += 1
        return "".join(result), offset_map

    # -------------------------------------------------------
    # トークン化（オフセット付き）
    # -------------------------------------------------------
    def _tokenize(self) -> tuple[list[str], list[int]]:
        pattern = "|".join(
            re.escape(k)
            for k in sorted(self.commands.keys(), key=len, reverse=True)
        )
        tokens = []
        offsets = []
        for m in re.finditer(pattern, self.clean_code):
            tokens.append(m.group())
            offsets.append(m.start())
        return tokens, offsets

    # -------------------------------------------------------
    # clean_code上のオフセット → 元ソースの行・列・行テキストに変換
    # -------------------------------------------------------
    def _offset_to_location(self, clean_offset: int) -> tuple[int, int, str]:
        """(line, col, line_text) を返す（1-indexed）"""
        orig_offset = self.offset_map[clean_offset]
        lines = self.original_code.splitlines(keepends=True)
        cumulative = 0
        for lineno, line in enumerate(lines, start=1):
            if cumulative + len(line) > orig_offset:
                col = orig_offset - cumulative + 1
                return lineno, col, line.rstrip("\n").rstrip("\r")
            cumulative += len(line)
        # 末尾の場合
        return len(lines), 1, (lines[-1].rstrip() if lines else "")

    # -------------------------------------------------------
    # SpikiCompileError を生成するヘルパー
    # -------------------------------------------------------
    def _compile_error(self, message: str, token_index: int) -> SpikiCompileError:
        clean_offset = self.token_offsets[token_index]
        token_str = self.tokens[token_index]
        line, col, line_text = self._offset_to_location(clean_offset)
        return SpikiCompileError(message, line, col, token_str, line_text)

    # -------------------------------------------------------
    # ブラケット対応チェック
    # -------------------------------------------------------
    def _build_bracket_map(self) -> dict[int, int]:
        # コマンドからスピキ語を逆引きするための辞書を作成
        rev_commands = {v: k for k, v in self.commands.items()}
        
        bracket_map = {}
        stack = []  # (token_index,) を積む
        for i, token in enumerate(self.tokens):
            cmd = self.commands[token]
            if cmd in ("[", "L"):
                stack.append(i)
            elif cmd == "]":
                if not stack:
                    # エラーメッセージをスピキ語にする
                    msg = f"対応する '{rev_commands['[']}' のない '{token}' があります"
                    raise self._compile_error(msg, i)
                
                start = stack.pop()
                bracket_map[start] = i
                bracket_map[i] = start

        # 閉じられていない開始タグを報告
        if stack:
            start_index = stack[0]
            start_token = self.tokens[start_index]
            msg = f"閉じられていない '{start_token}' があります"
            raise self._compile_error(msg, start_index)

        return bracket_map

    # -------------------------------------------------------
    # メイン実行ループ
    # -------------------------------------------------------
    def run(self):
        cells = [0] * self.CELL_SIZE
        ptr = 0
        pc = 0

        while pc < len(self.tokens):
            token = self.tokens[pc]
            cmd = self.commands[token]

            if cmd == "+":
                cells[ptr] = (cells[ptr] + 1) % 256

            elif cmd == "-":
                cells[ptr] = (cells[ptr] - 1) % 256

            # 【修正2】ポインタ境界チェック
            elif cmd == ">":
                ptr += 1
                if ptr >= self.CELL_SIZE:
                    raise SpikiError(
                        f"ポインタが右端を超えました（ptr={ptr}）"
                    )

            elif cmd == "<":
                ptr -= 1
                if ptr < 0:
                    raise SpikiError(
                        f"ポインタが左端を超えました（ptr={ptr}）"
                    )

            elif cmd == ".":
                print(chr(cells[ptr]), end="", flush=True)

            # 【修正4】, コマンド（入力）を実装
            elif cmd == ",":
                try:
                    # 1文字読み込む
                    ch = sys.stdin.read(1)
                    # 改行コード (\n や \r) だったら、次の文字が出るまで読み飛ばす
                    while ch in ('\n', '\r'):
                        ch = sys.stdin.read(1)
                    
                    cells[ptr] = ord(ch) if ch else 0
                except (EOFError, KeyboardInterrupt):
                    cells[ptr] = 0

            elif cmd == "[":
                if cells[ptr] == 0:
                    pc = self.bracket_map[pc]

            elif cmd == "]":
                if cells[ptr] != 0:
                    pc = self.bracket_map[pc]

            # 【修正3】L: ﾁｮﾜﾖｰﾁｮﾜﾖｰﾑﾙｺﾞﾜﾚｯｼﾞﾁｮﾜﾖｰ の独自動作
            # → セルが非ゼロならループ先頭へ（do-whileループ的な動作）
            elif cmd == "L":
                pass  # ループ先頭は常に通過（do-whileの開始点）

            elif cmd == "z":
                cells[ptr] = 0

            # 【修正6】i: 次の命令をスキップ（ブラケット考慮）
            elif cmd == "i":
                if cells[ptr] == 0:
                    pc += 1
                    # スキップ先が ] の場合はブラケットジャンプを優先しない
                    # （単純に1命令スキップ）

            # 【修正1】p コマンドを実装（現在のセルの値を10進数で出力）
            elif cmd == "p":
                print(cells[ptr], end="", flush=True)

            elif cmd == "q":
                break

            pc += 1


def main():
    # 【修正8】実行全体を try/except で包む
    try:
        if len(sys.argv) < 2:
            print("使用法: python spiki.py <ファイル名.ｽﾋﾟｷ!>")
            print("  ※ シェルによっては拡張子をクォートしてください。")
            return

        file_path = sys.argv[1]

        # 【修正9】拡張子チェックは警告にとどめ、実行は継続できるよう選択肢を提示
        if not file_path.endswith(".ｽﾋﾟｷ!"):
            print(
                f"警告: 拡張子が '.ｽﾋﾟｷ!' ではありません（'{file_path}'）。"
                " 実行を続けますか？ [y/N]: ",
                end="",
            )
            answer = input().strip().lower()
            if answer != "y":
                return

        if not os.path.exists(file_path):
            print(f"エラー: ファイル '{file_path}' が見つかりません。")
            return

        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        interpreter = SpikiInterpreter(code)
        interpreter.run()

    except SpikiCompileError as e:
        print(f"\n{e.format()}", file=sys.stderr)
        sys.exit(1)
    except SpikiError as e:
        print(f"\n[実行エラー] {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[中断されました]", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n[予期しないエラー] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()