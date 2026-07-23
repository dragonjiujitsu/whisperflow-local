from __future__ import annotations

from typing import Callable

import AppKit
import Foundation
import objc


class _Observer(Foundation.NSObject):
    def initWithCallback_(self, callback):
        self = objc.super(_Observer, self).init()
        if self is not None:
            self.callback = callback
        return self

    def willSleep_(self, notification) -> None:
        self.callback("sleep")

    def didWake_(self, notification) -> None:
        self.callback("wake")


class MacPowerMonitor:
    def __init__(self, callback: Callable[[str], None]) -> None:
        self._observer = _Observer.alloc().initWithCallback_(callback)
        self._center = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._center.addObserver_selector_name_object_(
            self._observer, "willSleep:", AppKit.NSWorkspaceWillSleepNotification, None
        )
        self._center.addObserver_selector_name_object_(
            self._observer, "didWake:", AppKit.NSWorkspaceDidWakeNotification, None
        )
        self._started = True

    def stop(self) -> None:
        if self._started:
            self._center.removeObserver_(self._observer)
            self._started = False
