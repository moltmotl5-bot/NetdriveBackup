#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
from typing import List

from netdriver_core.log import logman

__all__ = ["catch_error_of_output"]


log = logman.logger


def catch_error_of_output(output: str,
                          error_patterns: List[re.Pattern],
                          ignore_patterns: List[re.Pattern]) -> str | None:
    """ Catch error message from output by error patterns and ignore patterns
    :param output: output string
    :param error_patterns: list of error patterns
    :param ignore_patterns: list of ignore patterns
    :return: error message or None
    """
    log.debug("Catching errors in output.")
    output = output.replace("\r", "")
    for error_pattern in error_patterns:
        ematch: re.Match = error_pattern.search(output)
        if ematch:
            imatch: re.Match = None
            for ignore_pattern in ignore_patterns:
                imatch = ignore_pattern.search(output)
                if imatch:
                    log.debug(f"Ignoring error: {ematch.group()}, By pattern: {ignore_pattern}")
                    break
            if not imatch:
                caught = ematch.group().strip()
                log.debug(f"Catched an error: {caught}, By pattern: {error_pattern}")
                if caught == "^":
                    fuller = re.search(r"^% .+", output, re.MULTILINE)
                    if fuller:
                        return fuller.group().strip()
                    has_cli_error = re.search(
                        r"% Invalid|Command authorization failed|Command rejected|ERROR:",
                        output,
                        re.MULTILINE | re.IGNORECASE,
                    )
                    has_enable_prompt = re.search(r"^[^\s#]+#\s*$", output, re.MULTILINE)
                    if not has_cli_error and has_enable_prompt and len(output) > 200:
                        log.debug(
                            "Ignoring lone ^ in long output with enable prompt (false positive)"
                        )
                        continue
                return ematch.group()
    log.debug("No errors found in output")
    return None


def catch_auto_confirm_of_output(output: str, 
                                 auto_confirm_patterns: dict[re.Pattern, str]) -> str | None:
    log.debug("Catching auto confirm in output.")
    output = output.replace("\r", "")
    for pattern, confirm_cmd in auto_confirm_patterns.items():
        if pattern.search(output):
            return confirm_cmd
    log.debug("No auto confirm found in output")
    return None


def remove_suffix(text: str, suffix: str) -> str:
    """ Remove suffix from text
    :param text: text
    :param suffix: suffix
    :return: text without suffix
    """
    if text.endswith(suffix):
        return text[:-len(suffix)]
    return text