"""测试包标记。

CI 用 `python3 -m unittest discover -s tests`，这条命令要求 tests 是一个
可导入的包；缺了 __init__.py 会直接报 "Start directory is not importable"。
pytest 不挑这个，所以本地一直没暴露。
"""
