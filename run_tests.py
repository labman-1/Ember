#!/usr/bin/env python3
"""
测试运行脚本
用法:
    python run_tests.py              # 运行所有测试
    python run_tests.py -v           # 详细输出
    python run_tests.py -k thread    # 只运行线程相关测试
"""
import sys
import subprocess
import argparse


def main():
    parser = argparse.ArgumentParser(description="运行 Ember 测试套件")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    parser.add_argument("-k", "--keyword", help="只运行匹配关键字的测试")
    parser.add_argument("--cov", action="store_true", help="生成覆盖率报告")
    parser.add_argument("-x", "--exitfirst", action="store_true", help="遇到第一个失败就停止")

    args = parser.parse_args()

    # 构建 pytest 命令
    cmd = ["python", "-m", "pytest", "tests/"]

    if args.verbose:
        cmd.append("-v")

    if args.keyword:
        cmd.extend(["-k", args.keyword])

    if args.cov:
        cmd.extend(["--cov=.", "--cov-report=term-missing"])

    if args.exitfirst:
        cmd.append("-x")

    # 添加默认参数
    cmd.extend(["--tb=short", "-ra"])

    print(f"运行: {' '.join(cmd)}")
    print("=" * 60)

    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
