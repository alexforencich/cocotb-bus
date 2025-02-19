# Copyright cocotb contributors
# Copyright (c) 2013 Potential Ventures Ltd
# Copyright (c) 2013 SolarFlare Communications Inc
# Licensed under the Revised BSD License, see LICENSE for details.
# SPDX-License-Identifier: BSD-3-Clause

"""Common bus related functionality.
A bus is simply defined as a collection of signals.
"""

import warnings

import cocotb
from cocotb.handle import _AssignmentResult

def _build_sig_attr_dict(signals):
    if isinstance(signals, dict):
        return signals
    else:
        return {sig: sig for sig in signals}


class Bus:
    """Wraps up a collection of signals.

    Assumes we have a set of signals/nets named ``entity.<bus_name><separator><signal>``.

    For example a bus ``stream_in`` with signals ``valid`` and ``data`` is assumed
    to be named ``dut.stream_in_valid`` and ``dut.stream_in_data`` (with
    the default separator '_').

    TODO:
        Support for ``struct``/``record`` ports where signals are member names.
    """

    def __init__(self, entity, name, signals, optional_signals=[], bus_separator="_", case_insensitive=True, array_idx=None):
        """
        Args:
            entity (SimHandle): :any:`SimHandle` instance to the entity containing the bus.
            name (str): Name of the bus. ``None`` for a nameless bus, e.g. bus-signals
                in an interface or a ``modport`` (untested on ``struct``/``record``,
                but could work here as well).
            signals (list or dict): In the case of an object (passed to :func:`drive`/:func:`capture`)
                that has the same attribute names as the signal names of the bus,
                the *signals* argument can be a list of those names.
                When the object has different attribute names, the *signals* argument should be
                a dict that maps bus attribute names to object signal names.
            optional_signals (list or dict, optional): Signals that don't have to be present
                on the interface.
                See the *signals* argument above for details.
            bus_separator (str, optional): Character(s) to use as separator between bus
                name and signal name. Defaults to '_'.
            case_insensitive (bool, optional): Perform case-insensitive match on signal names.
                Defaults to True.
            array_idx (int or None, optional): Optional index when signal is an array.
        """
        self._entity = entity
        self._name = name
        self._signals = {}
        for attr_name, sig_name in _build_sig_attr_dict(signals).items():
            if name:
                signame = name + bus_separator + sig_name
            else:
                signame = sig_name

            self._add_signal(attr_name, signame, array_idx, case_insensitive)

        # Also support a set of optional signals that don't have to be present
        for attr_name, sig_name in _build_sig_attr_dict(optional_signals).items():
            if name:
                signame = name + bus_separator + sig_name
            else:
                signame = sig_name
            # Signal matching on optional attributes needs to be also case insensitive
            self._entity._log.debug("Signal name {}".format(signame))
            if self._caseInsensGetattr(entity, signame) is not None:
                self._add_signal(attr_name, signame, array_idx, case_insensitive)
            else:
                self._entity._log.debug("Ignoring optional missing signal "
                                        "%s on bus %s" % (sig_name, name))

    def _caseInsensGetattr(self, obj, attr):
        # dir breaks verilator, so avoid calling it if possible
        for a in (attr, attr.upper(), attr.lower()):
            if hasattr(obj, a):
                return getattr(obj, a)
        if cocotb.SIM_NAME.lower().startswith("verilator"):
            warnings.warn(
                "Using dir() for case-insensitive matching;"
                "this may trigger a known Verilator bug",
                RuntimeWarning,
            )
        for a in dir(obj):
            if a.casefold() == attr.casefold():
                return getattr(obj, a)
        return None

    def _add_signal(self, attr_name, signame, array_idx=None, case_insensitive=True):
        self._entity._log.debug("Signal name {}, idx {}".format(signame, array_idx))
        if case_insensitive:
            handle = self._caseInsensGetattr(self._entity, signame)
        else:
            handle = getattr(self._entity, signame)
        if array_idx is not None:
            handle = handle[array_idx]
        setattr(self, attr_name, handle)
        self._signals[attr_name] = getattr(self, attr_name)

    def drive(self, obj, strict=False):
        """Drives values onto the bus.

        Args:
            obj: Object with attribute names that match the bus signals.
            strict (bool, optional): Check that all signals are being assigned.

        Raises:
            AttributeError: If not all signals have been assigned when ``strict=True``.
        """
        for attr_name, hdl in self._signals.items():
            if not hasattr(obj, attr_name):
                if strict:
                    msg = ("Unable to drive onto {0}.{1} because {2} is missing "
                           "attribute {3}".format(self._entity._name,
                                                  self._name,
                                                  type(obj).__qualname__,
                                                  attr_name))
                    raise AttributeError(msg)
                else:
                    continue
            val = getattr(obj, attr_name)
            hdl.value = val

    def capture(self):
        """Capture the values from the bus, returning an object representing the capture.

        Returns:
            dict: A dictionary that supports access by attribute,
            where each attribute corresponds to each signal's value.
        Raises:
            RuntimeError: If signal not present in bus,
                or attempt to modify a bus capture.
        """
        class _Capture(dict):
            def __getattr__(self, name):
                if name in self:
                    return self[name]
                else:
                    raise RuntimeError('Signal {} not present in bus'.format(name))

            def __setattr__(self, name, value):
                raise RuntimeError('Modifying a bus capture is not supported')

            def __delattr__(self, name):
                raise RuntimeError('Modifying a bus capture is not supported')

        _capture = _Capture()
        for attr_name, hdl in self._signals.items():
            _capture[attr_name] = hdl.value

        return _capture

    def sample(self, obj, strict=False):
        """Sample the values from the bus, assigning them to *obj*.

        Args:
            obj: Object with attribute names that match the bus signals.
            strict (bool, optional): Check that all signals being sampled
                are present in *obj*.

        Raises:
            AttributeError: If attribute is missing in *obj* when ``strict=True``.
        """
        for attr_name, hdl in self._signals.items():
            if not hasattr(obj, attr_name):
                if strict:
                    msg = ("Unable to sample from {0}.{1} because {2} is missing "
                           "attribute {3}".format(self._entity._name,
                                                  self._name,
                                                  type(obj).__qualname__,
                                                  attr_name))
                    raise AttributeError(msg)
                else:
                    continue
            # Try to use the get/set_binstr methods because they will not clobber the properties
            # of obj.attr_name on assignment.  Otherwise use setattr() to crush whatever type of
            # object was in obj.attr_name with hdl.value:
            try:
                getattr(obj, attr_name).set_binstr(hdl.value.get_binstr())
            except AttributeError:
                setattr(obj, attr_name, hdl.value)

    def __le__(self, value):
        """Overload the less than or equal to operator for value assignment"""
        self.drive(value)
        return _AssignmentResult(self, value)
