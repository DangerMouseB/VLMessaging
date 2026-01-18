# **********************************************************************************************************************
# Copyright 2026 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# intended to be drop-in replacement for Python's logging module with some extra features
# - context manager for temporary configuration
# - TRACE logging level
# - NO_LOG level to disable logging
# - composable function implementations
# - Uses Sink as suffix rather than Handler
# - adds ListSink, StreamSink, FileSink classes
# - pipe style logging syntax: 'message' >> logger.debug
# - pipe style sinking: logger >> sink
# - '*' and 'module.*' syntax for clearly enabling logging for modules and sub-modules. '*' at any level are done
#   before other definitions at the same level.

# NOTES
# - don't want to have to change code to use different levels of logging
#
# DO'S AND DON'TS
# - DON'T call setLevel in the module
# - DO use the configure context manager to set up temporary logging configuration
# - Where relevant use disabled=True on logger creation to reduce logging to a property access and a function call (will
#   be enabled in the context manager).
# - DON'T use the logger framework for confidential information since it is too easy to broadcast it to the wrong place


# type imports
from collections.abc import MutableSequence

# Python imports
import io, contextlib, threading, logging
from logging import *

__all__ = [
    # defined in standard Python logging module
    'BASIC_FORMAT', 'BufferingFormatter', 'CRITICAL', 'DEBUG', 'ERROR', 'FATAL', 'FileHandler', 'Filter', 'Formatter',
    'Handler', 'INFO', 'LogRecord', 'Logger', 'LoggerAdapter', 'NOTSET', 'NullHandler', 'StreamHandler', 'WARN',
    'WARNING', 'addLevelName', 'basicConfig', 'captureWarnings', 'critical', 'debug', 'disable', 'error', 'exception',
    'fatal', 'getLevelName', 'getLogger', 'getLoggerClass', 'info', 'log', 'makeLogRecord', 'setLoggerClass',
    'shutdown', 'warn', 'warning', 'getLogRecordFactory', 'setLogRecordFactory', 'lastResort', 'raiseExceptions',
    'getLevelNamesMapping',
    # defined here
    'ListSink', 'StreamSink', 'FileSink', 'enable', 'configure', 'TRACE', 'NO_LOG',
]


addLevelName(TRACE:=5, 'TRACE')
addLevelName(NO_LOG:=1000, 'NO_LOG')


# **********************************************************************************************************************
# Sinks
# **********************************************************************************************************************

class StreamSink(logging.StreamHandler):
    __slots__ = ['minLevel', 'maxLevel']
    def __init__(self, stream=None, *, minLevel=1, maxLevel=CRITICAL, formatter=None):
        super().__init__(stream)
        self.minLevel = logging._checkLevel(minLevel)
        self.maxLevel = logging._checkLevel(maxLevel)
        if formatter is not None:
            self.setFormatter(formatter)
    def __rrshift__(self, logger):
        logger.addHandler(self)
        return logger
    def setLevel(self, level):
        """
        Set the logging level of this handler.  level must be an int or a str.
        """
        self.minLevel = logging._checkLevel(level)
        return self
    def emit(self, record):
        if self.minLevel <= record.levelno <= self.maxLevel:
            super().emit(record)
    def __repr__(self):
        minLevel = getLevelName(self.minLevel)
        maxLevel = getLevelName(self.maxLevel)
        return '<%s (%s-%s)>' % (self.__class__.__name__, minLevel, maxLevel)


class FileSink(logging.FileHandler):
    __slots__ = ['minLevel', 'maxLevel']
    def __init__(self, filename, mode='a', encoding=None, delay=False, errors=None, *, minLevel=1, maxLevel=CRITICAL, formatter=None):
        super().__init__(filename, mode, encoding, delay, errors)
        self.minLevel = logging._checkLevel(minLevel)
        self.maxLevel = logging._checkLevel(maxLevel)
        if formatter is not None:
            self.setFormatter(formatter)
    def __rrshift__(self, logger):
        logger.addHandler(self)
        return logger
    def setLevel(self, level):
        """
        Set the logging level of this handler.  level must be an int or a str.
        """
        self.minLevel = logging._checkLevel(level)
        return self
    def emit(self, record):
        if self.minLevel <= record.levelno <= self.maxLevel:
            super().emit(record)
    def __repr__(self):
        minLevel = getLevelName(self.minLevel)
        maxLevel = getLevelName(self.maxLevel)
        return '<%s (%s-%s)>' % (self.__class__.__name__, minLevel, maxLevel)


class ListSink(logging.Handler):
    __slots__ = ['minLevel', 'maxLevel']
    """Handler that stores log records in a list."""
    def __init__(self, seq:MutableSequence[str], *, minLevel=1, maxLevel=CRITICAL, formatter=None):
        super().__init__()
        self.minLevel = logging._checkLevel(minLevel)
        self.maxLevel = logging._checkLevel(maxLevel)
        self.seq = seq
    def __rrshift__(self, logger):
        logger.addHandler(self)
        return logger
    def setLevel(self, level):
        """
        Set the logging level of this handler.  level must be an int or a str.
        """
        self.minLevel = logging._checkLevel(level)
        return self
    def emit(self, record):
        if self.minLevel <= record.levelno <= self.maxLevel:
            self.seq.append(self.format(record))
    def __repr__(self):
        minLevel = getLevelName(self.minLevel)
        maxLevel = getLevelName(self.maxLevel)
        return '<%s (%s-%s)>' % (self.__class__.__name__, minLevel, maxLevel)


# **********************************************************************************************************************
# enable and configure context managers
# **********************************************************************************************************************

@contextlib.contextmanager
def enable(*patterns):
    """
    Context manager to temporarily enable loggers matching patterns.

    Patterns can be:
    - 'A' - exact match for logger named 'A'
    - 'A.*' - match all children of A (e.g., 'A.B', 'A.B.C')
    - '*' - match all loggers

    Example:
        with logging.enable('A.*'):
            'msg' >> loggerA_B.warning  # will log even if loggerA_B was disabled
    """
    # Find all matching loggers and store their original disabled state
    original_states = {}

    for pattern in patterns:
        if pattern == '*':
            # Enable all loggers
            for name, logger in logging.Logger.manager.loggerDict.items():
                if isinstance(logger, logging.Logger):
                    original_states[name] = logger.disabled
                    logger.disabled = False
            # Also handle root logger
            root = logging.getLogger()
            original_states[''] = root.disabled
            root.disabled = False
        elif pattern.endswith('.*'):
            # Enable all children
            prefix = pattern[:-1]  # Remove '*'
            for name, logger in logging.Logger.manager.loggerDict.items():
                if isinstance(logger, logging.Logger):
                    if name.startswith(prefix):
                        original_states[name] = logger.disabled
                        logger.disabled = False
        else:
            # Exact match
            logger = logging.getLogger(pattern)
            original_states[pattern] = logger.disabled
            logger.disabled = False

    try:
        yield
    finally:
        # Restore original states
        for name, was_disabled in original_states.items():
            logger = logging.getLogger(name)
            logger.disabled = was_disabled


@contextlib.contextmanager
def configure(levels=None):
    """
    Context manager to temporarily configure logger levels.

    Args:
        levels: dict mapping patterns to log levels
            - '*' - match all loggers (root)
            - 'A' - exact match for logger named 'A'
            - 'A.*' - match logger 'A' and all children

    Example:
        with logging.configure(levels={
            '*': logging.ERROR,
            'A': logging.WARNING,
            'A.B': logging.DEBUG,
        }):
            # loggers temporarily have these levels
            pass
    """
    if levels is None:
        yield
        return None

    original_levels = {}

    # Process patterns in order: '*' first, then specific, then wildcards
    # This ensures more specific patterns override general ones
    sorted_patterns = sorted(levels.keys(), key=lambda p: (p != '*', not p.endswith('.*'), p))

    for pattern in sorted_patterns:
        level = levels[pattern]

        if pattern == '*':
            # Set root logger level
            root = logging.getLogger()
            original_levels.setdefault('', root.level)
            root.setLevel(level)
            # Set all existing loggers
            for name, logger in logging.Logger.manager.loggerDict.items():
                if isinstance(logger, logging.Logger):
                    original_levels.setdefault(name, logger.level)
                    logger.setLevel(level)
        elif pattern.endswith('.*'):
            # Set all children
            prefix = pattern[:-1]
            for name, logger in logging.Logger.manager.loggerDict.items():
                if isinstance(logger, logging.Logger):
                    if name == prefix or name.startswith(prefix):
                        original_levels.setdefault(name, logger.level)
                        logger.setLevel(level)
        else:
            # Exact match
            logger = logging.getLogger(pattern)
            original_levels.setdefault(pattern, logger.level)
            logger.setLevel(level)

    try:
        yield
    finally:
        # Restore original levels
        for name, orig_level in original_levels.items():
            logger = logging.getLogger(name)
            logger.setLevel(orig_level)


# **********************************************************************************************************************
# Logger replacement with >> operator
# **********************************************************************************************************************

class _PipeLogger:
    """Logger wrapper that supports piping arguments with >> operator."""

    __slots__ = ('_logger', '_name', '_trace', '_debug', '_info', '_warning', '_error', '_critical', '_nop')

    def __init__(self, logger):
        self._logger = logger
        self._name = logger.name
        self._trace = _LogFn(self, TRACE)
        self._debug = _LogFn(self, DEBUG)
        self._info = _LogFn(self, INFO)
        self._warning = _LogFn(self, WARNING)
        self._error = _LogFn(self, ERROR)
        self._critical = _LogFn(self, CRITICAL)
        self._nop = _NoPipe()

    def setLevel(self, level):
        """
        Set the logging level of this logger.  level must be an int or a str.
        """
        self._logger.setLevel(level)
        return self

    @property
    def trace(self):
        return self._trace if not self._logger.disabled else self._nop

    @property
    def debug(self):
        return self._debug if not self._logger.disabled else self._nop

    @property
    def info(self):
        return self._info if not self._logger.disabled else self._nop

    @property
    def warning(self):
        return self._warning if not self._logger.disabled else self._nop

    @property
    def error(self):
        return self._error if not self._logger.disabled else self._nop

    @property
    def critical(self):
        return self._critical if not self._logger.disabled else self._nop

    @property
    def enable(self):
        self._logger.disabled = False
        return self

    @property
    def disabled(self):
        return self._logger.disabled

    @property
    def disable(self):
        self._logger.disabled = True
        return self

    def isEnabledFor(self, level):
        """
        Is this logger enabled for level 'level'?
        """
        return self._logger.isEnabledFor(level)

    def addHandler(self, hdlr):
        """
        Add the specified handler to this logger.
        """
        self._logger.addHandler(hdlr)
        return self

    def removeHandler(self, hdlr):
        """
        Remove the specified handler from this logger.
        """
        self._logger.removeHandler(hdlr)
        return self

    @property
    def level(self):
        return self._logger.level

    @property
    def name(self):
        return self._name

    @property
    def handlers(self):
        return self._logger.handlers


class _NoPipe:
    def __rrshift__(self, msgOrArgs):
        return msgOrArgs
    def __call__(self, *args, **kwargs):
        pass


class _LogFn:
    """Helper class that accepts >> operator for logging."""

    __slots__ = ('_logger', '_level')

    def __init__(self, logger, level):
        self._logger = logger
        self._level = level

    def __rrshift__(self, msgOrArgs):
        """Handle >> operator: args >> logger.level"""
        if not self._logger.disabled and self._logger._logger.isEnabledFor(self._level):
            if isinstance(msgOrArgs, tuple):
                self._logger._logger._log(self._level, msgOrArgs[0], msgOrArgs[1:], stacklevel=2)
            else:
                self._logger._logger._log(self._level, msgOrArgs, (), stacklevel=2)
        return msgOrArgs

    def __call__(self, *args, **kwargs):
        """Allow normal function call syntax."""
        if not self._logger.disabled and self._logger._logger.isEnabledFor(self._level):
            self._logger._logger._log(self._level, args[0], args[1:], stacklevel=2, **kwargs)
        return self._logger

_pipe_loggers = {}
_pipe_loggers_lock = threading.Lock()

def getLogger(name=None):
    with _pipe_loggers_lock:
        if name not in _pipe_loggers:
            _pipe_loggers[name] = _PipeLogger(logging.getLogger(name))
        return _pipe_loggers[name]
