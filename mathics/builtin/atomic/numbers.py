# cython: language_level=3
# -*- coding: utf-8 -*-

# Note: docstring is flowed in documentation. Line breaks in the docstring will appear in the
# printed output, so be carful not to add then mid-sentence.

"""
Representation of Numbers

Integers and Real numbers with any number of digits, automatically tagging numerical preceision when appropriate.

Precision is not "guarded" through the evaluation process. Only integer precision is supported.
However, things like 'N[Pi, 100]' should work as expected.
"""

import sympy
import mpmath
import math
import hashlib
import zlib
from collections import namedtuple
from contextlib import contextmanager
from itertools import chain
from functools import lru_cache


from mathics.builtin.base import Builtin, Predefined
from mathics.core.convert import from_sympy
from mathics.core.evaluators import apply_N

from mathics.core.expression import Expression
from mathics.core.symbols import (
    Symbol,
    SymbolFalse,
    SymbolList,
    SymbolTrue,
)
from mathics.core.atoms import (
    Complex,
    Integer,
    Integer0,
    MachineReal,
    Rational,
    Real,
    String,
    from_python,
)


from mathics.core.number import (
    dps,
    convert_int_to_digit_list,
    machine_precision,
    machine_epsilon,
)

from mathics.core.attributes import (
    listable,
    numeric_function,
    protected,
    read_protected,
)


@lru_cache(maxsize=1024)
def log_n_b(py_n, py_b) -> int:
    return int(mpmath.ceil(mpmath.log(py_n, py_b))) if py_n != 0 and py_n != 1 else 1


def check_finite_decimal(denominator):
    # The rational number is finite decimal if the denominator has form 2^a * 5^b
    while denominator % 5 == 0:
        denominator = denominator / 5

    while denominator % 2 == 0:
        denominator = denominator / 2

    return True if denominator == 1 else False


def chop(expr, delta=10.0 ** (-10.0)):
    if isinstance(expr, Real):
        if expr.is_nan(expr):
            return expr
        if -delta < expr.get_float_value() < delta:
            return Integer0
    elif isinstance(expr, Complex) and expr.is_inexact():
        real, imag = expr.real, expr.imag
        if -delta < real.get_float_value() < delta:
            real = Integer0
        if -delta < imag.get_float_value() < delta:
            imag = Integer0
        return Complex(real, imag)
    elif isinstance(expr, Expression):
        return Expression(chop(expr.head), *[chop(leaf) for leaf in expr.leaves])
    return expr


def convert_repeating_decimal(numerator, denominator, base):
    head = [x for x in str(numerator // denominator)]
    tails = []
    subresults = [numerator % denominator]
    numerator %= denominator

    while numerator != 0:  # only rational input can go to this case
        numerator *= base
        result_digit, numerator = divmod(numerator, denominator)
        tails.append(str(result_digit))
        if numerator not in subresults:
            subresults.append(numerator)
        else:
            break

    for i in range(len(head) - 1, -1, -1):
        j = len(tails) - 1
        if head[i] != tails[j]:
            break
        else:
            del tails[j]
            tails.insert(0, head[i])
            del head[i]
            j = j - 1

    # truncate all leading 0's
    if all(elem == "0" for elem in head):
        for i in range(0, len(tails)):
            if tails[0] == "0":
                tails = tails[1:] + [str(0)]
            else:
                break
    return (head, tails)


def convert_float_base(x, base, precision=10):

    length_of_int = 0 if x == 0 else int(mpmath.log(x, base))
    # iexps = list(range(length_of_int, -1, -1))

    def convert_int(x, base, exponents):
        out = []
        for e in range(0, exponents + 1):
            d = x % base
            out.append(d)
            x = x / base
            if x == 0:
                break
        out.reverse()
        return out

    def convert_float(x, base, exponents):
        out = []
        for e in range(0, exponents):
            d = int(x * base)
            out.append(d)
            x = (x * base) - d
            if x == 0:
                break
        return out

    int_part = convert_int(int(x), base, length_of_int)
    if isinstance(x, (float, sympy.Float)):
        # fexps = list(range(-1, -int(precision + 1), -1))
        real_part = convert_float(x - int(x), base, precision + 1)
        return int_part + real_part
    elif isinstance(x, int):
        return int_part
    else:
        raise TypeError(x)


class Chop(Builtin):
    """
    <dl>
      <dt>'Chop[$expr$]'
      <dd>replaces floating point numbers close to 0 by 0.

      <dt>'Chop[$expr$, $delta$]'
      <dd>uses a tolerance of $delta$. The default tolerance is '10^-10'.
    </dl>

    >> Chop[10.0 ^ -16]
     = 0
    >> Chop[10.0 ^ -9]
     = 1.*^-9
    >> Chop[10 ^ -11 I]
     = I / 100000000000
    >> Chop[0. + 10 ^ -11 I]
     = 0
    """

    messages = {
        "tolnn": "Tolerance specification a must be a non-negative number.",
    }

    rules = {
        "Chop[expr_]": "Chop[expr, 10^-10]",
    }

    summary_text = "set sufficiently small numbers or imaginary parts to zero"

    def apply(self, expr, delta, evaluation):
        "Chop[expr_, delta_:(10^-10)]"

        delta = delta.round_to_float(evaluation)
        if delta is None or delta < 0:
            return evaluation.message("Chop", "tolnn")

        return chop(expr, delta=delta)


class Fold(object):
    # allows inherited classes to specify a single algorithm implementation that
    # can be called with machine precision, arbitrary precision or symbolically.

    ComputationFunctions = namedtuple("ComputationFunctions", ("sin", "cos"))

    FLOAT = 0
    MPMATH = 1
    SYMBOLIC = 2

    math = {
        FLOAT: ComputationFunctions(
            cos=math.cos,
            sin=math.sin,
        ),
        MPMATH: ComputationFunctions(
            cos=mpmath.cos,
            sin=mpmath.sin,
        ),
        SYMBOLIC: ComputationFunctions(
            cos=lambda x: Expression("Cos", x),
            sin=lambda x: Expression("Sin", x),
        ),
    }

    operands = {
        FLOAT: lambda x: None if x is None else x.round_to_float(),
        MPMATH: lambda x: None if x is None else x.to_mpmath(),
        SYMBOLIC: lambda x: x,
    }

    def _operands(self, state, steps):
        raise NotImplementedError

    def _fold(self, state, steps, math):
        raise NotImplementedError

    def _spans(self, operands):
        spans = {}
        k = 0
        j = 0

        for mode in (self.FLOAT, self.MPMATH):
            for i, operand in enumerate(operands[k:]):
                if operand[0] > mode:
                    break
                j = i + k + 1

            if k == 0 and j == 1:  # only init state? then ignore.
                j = 0

            spans[mode] = slice(k, j)
            k = j

        spans[self.SYMBOLIC] = slice(k, len(operands))

        return spans

    def fold(self, x, ll):
        # computes fold(x, ll) with the internal _fold function. will start
        # its evaluation machine precision, and will escalate to arbitrary
        # precision if or symbolical evaluation only if necessary. folded
        # items already computed are carried over to new evaluation modes.

        yield x  # initial state

        init = None
        operands = list(self._operands(x, ll))
        spans = self._spans(operands)

        for mode in (self.FLOAT, self.MPMATH, self.SYMBOLIC):
            s_operands = [y[1:] for y in operands[spans[mode]]]

            if not s_operands:
                continue

            if mode == self.MPMATH:
                from mathics.core.number import min_prec

                precision = min_prec(*[t for t in chain(*s_operands) if t is not None])
                working_precision = mpmath.workprec
            else:

                @contextmanager
                def working_precision(_):
                    yield

                precision = None

            if mode == self.FLOAT:

                def out(z):
                    return Real(z)

            elif mode == self.MPMATH:

                def out(z):
                    return Real(z, precision)

            else:

                def out(z):
                    return z

            as_operand = self.operands.get(mode)

            def converted_operands():
                for y in s_operands:
                    yield tuple(as_operand(t) for t in y)

            with working_precision(precision):
                c_operands = converted_operands()

                if init is not None:
                    c_init = tuple(
                        (None if t is None else as_operand(from_python(t)))
                        for t in init
                    )
                else:
                    c_init = next(c_operands)
                    init = tuple((None if t is None else out(t)) for t in c_init)

                generator = self._fold(c_init, c_operands, self.math.get(mode))

                for y in generator:
                    y = tuple(out(t) for t in y)
                    yield y
                    init = y


class IntegerDigits(Builtin):
    """
    <dl>
    <dt>'IntegerDigits[$n$]'
        <dd>returns a list of the base-10 digits in the integer $n$.
    <dt>'IntegerDigits[$n$, $base$]'
        <dd>returns a list of the base-$base$ digits in $n$.
    <dt>'IntegerDigits[$n$, $base$, $length$]'
        <dd>returns a list of length $length$, truncating or padding
        with zeroes on the left as necessary.
    </dl>

    >> IntegerDigits[76543]
     = {7, 6, 5, 4, 3}

    The sign of $n$ is discarded:
    >> IntegerDigits[-76543]
     = {7, 6, 5, 4, 3}

    >> IntegerDigits[15, 16]
     = {15}
    >> IntegerDigits[1234, 16]
     = {4, 13, 2}
    >> IntegerDigits[1234, 10, 5]
     = {0, 1, 2, 3, 4}

    #> IntegerDigits[1000, 10]
     = {1, 0, 0, 0}

    #> IntegerDigits[0]
     = {0}
    """

    attributes = listable | protected

    messages = {
        "int": "Integer expected at position 1 in `1`",
        "ibase": "Base `1` is not an integer greater than 1.",
    }

    rules = {
        "IntegerDigits[n_]": "IntegerDigits[n, 10]",
    }

    def apply_len(self, n, base, length, evaluation):
        "IntegerDigits[n_, base_, length_]"

        if not (isinstance(length, Integer) and length.get_int_value() >= 0):
            return evaluation.message("IntegerDigits", "intnn")

        return self.apply(n, base, evaluation, nr_elements=length.get_int_value())

    def apply(self, n, base, evaluation, nr_elements=None):
        "IntegerDigits[n_, base_]"

        if not (isinstance(n, Integer)):
            return evaluation.message(
                "IntegerDigits", "int", Expression("IntegerDigits", n, base)
            )

        if not (isinstance(base, Integer) and base.get_int_value() > 1):
            return evaluation.message("IntegerDigits", "ibase", base)

        if nr_elements == 0:
            # trivial case: we don't want any digits
            return Expression(SymbolList)

        digits = convert_int_to_digit_list(n.get_int_value(), base.get_int_value())

        if nr_elements is not None:
            if len(digits) >= nr_elements:
                # Truncate, preserving the digits on the right
                digits = digits[-nr_elements:]
            else:
                # Pad with zeroes
                digits = [0] * (nr_elements - len(digits)) + digits

        return Expression(SymbolList, *digits)


class MaxPrecision(Predefined):
    """
    <dl>
      <dt>'$MaxPrecision'
      <dd>represents the maximum number of digits of precision permitted in abitrary-precision numbers.
    </dl>

    >> $MaxPrecision
     = Infinity

    >> $MaxPrecision = 10;

    >> N[Pi, 11]
     : Requested precision 11 is larger than $MaxPrecision. Using current $MaxPrecision of 10. instead. $MaxPrecision = Infinity specifies that any precision should be allowed.
     = 3.141592654

    #> N[Pi, 10]
     = 3.141592654

    #> $MaxPrecision = x
     : Cannot set $MaxPrecision to x; value must be a positive number or Infinity.
     = x
    #> $MaxPrecision = -Infinity
     : Cannot set $MaxPrecision to -Infinity; value must be a positive number or Infinity.
     = -Infinity
    #> $MaxPrecision = 0
     : Cannot set $MaxPrecision to 0; value must be a positive number or Infinity.
     = 0
    #> $MaxPrecision = Infinity;

    #> $MinPrecision = 15;
    #> $MaxPrecision = 10
     : Cannot set $MaxPrecision such that $MaxPrecision < $MinPrecision.
     = 10
    #> $MaxPrecision
     = Infinity
    #> $MinPrecision = 0;
    """

    messages = {
        "precset": "Cannot set `1` to `2`; value must be a positive number or Infinity.",
        "preccon": "Cannot set `1` such that $MaxPrecision < $MinPrecision.",
    }

    name = "$MaxPrecision"

    rules = {
        "$MaxPrecision": "Infinity",
    }

    summary_text = "settable global maximum precision bound"


class MachineEpsilon_(Predefined):
    """
    <dl>
    <dt>'$MachineEpsilon'
        <dd>is the distance between '1.0' and the next
            nearest representable machine-precision number.
    </dl>

    >> $MachineEpsilon
     = 2.22045*^-16

    >> x = 1.0 + {0.4, 0.5, 0.6} $MachineEpsilon;
    >> x - 1
     = {0., 0., 2.22045*^-16}
    """

    name = "$MachineEpsilon"

    def evaluate(self, evaluation):
        return MachineReal(machine_epsilon)


class MachinePrecision_(Predefined):
    """
    <dl>
    <dt>'$MachinePrecision'
        <dd>is the number of decimal digits of precision for
            machine-precision numbers.
    </dl>

    >> $MachinePrecision
     = 15.9546
    """

    name = "$MachinePrecision"

    rules = {
        "$MachinePrecision": "N[MachinePrecision]",
    }


class MachinePrecision(Predefined):
    """
    <dl>
    <dt>'MachinePrecision'
        <dd>represents the precision of machine precision numbers.
    </dl>

    >> N[MachinePrecision]
     = 15.9546
    >> N[MachinePrecision, 30]
     = 15.9545897701910033463281614204

    #> N[E, MachinePrecision]
     = 2.71828

    #> Round[MachinePrecision]
     = 16
    """

    rules = {
        "N[MachinePrecision, prec_]": ("N[Log[10, 2] * %i, prec]" % machine_precision),
    }


class MinPrecision(Builtin):
    """
    <dl>
      <dt>'$MinPrecision'
      <dd>represents the minimum number of digits of precision permitted in abitrary-precision numbers.
    </dl>

    >> $MinPrecision
     = 0

    >> $MinPrecision = 10;

    >> N[Pi, 9]
     : Requested precision 9 is smaller than $MinPrecision. Using current $MinPrecision of 10. instead.
     = 3.141592654

    #> N[Pi, 10]
     = 3.141592654

    #> $MinPrecision = x
     : Cannot set $MinPrecision to x; value must be a non-negative number.
     = x
    #> $MinPrecision = -Infinity
     : Cannot set $MinPrecision to -Infinity; value must be a non-negative number.
     = -Infinity
    #> $MinPrecision = -1
     : Cannot set $MinPrecision to -1; value must be a non-negative number.
     = -1
    #> $MinPrecision = 0;

    #> $MaxPrecision = 10;
    #> $MinPrecision = 15
     : Cannot set $MinPrecision such that $MaxPrecision < $MinPrecision.
     = 15
    #> $MinPrecision
     = 0
    #> $MaxPrecision = Infinity;
    """

    messages = {
        "precset": "Cannot set `1` to `2`; value must be a non-negative number.",
        "preccon": "Cannot set `1` such that $MaxPrecision < $MinPrecision.",
    }

    name = "$MinPrecision"

    rules = {
        "$MinPrecision": "0",
    }

    summary_text = "settable global minimum precision bound"


class N(Builtin):
    """
    <dl>
    <dt>'N[$expr$, $prec$]'
        <dd>evaluates $expr$ numerically with a precision of $prec$ digits.
    </dl>
    >> N[Pi, 50]
     = 3.1415926535897932384626433832795028841971693993751

    >> N[1/7]
     = 0.142857

    >> N[1/7, 5]
     = 0.14286

    You can manually assign numerical values to symbols.
    When you do not specify a precision, 'MachinePrecision' is taken.
    >> N[a] = 10.9
     = 10.9
    >> a
     = a

    'N' automatically threads over expressions, except when a symbol has
     attributes 'NHoldAll', 'NHoldFirst', or 'NHoldRest'.
    >> N[a + b]
     = 10.9 + b
    >> N[a, 20]
     = a
    >> N[a, 20] = 11;
    >> N[a + b, 20]
     = 11.000000000000000000 + b
    >> N[f[a, b]]
     = f[10.9, b]
    >> SetAttributes[f, NHoldAll]
    >> N[f[a, b]]
     = f[a, b]

    The precision can be a pattern:
    >> N[c, p_?(#>10&)] := p
    >> N[c, 3]
     = c
    >> N[c, 11]
     = 11.000000000

    You can also use 'UpSet' or 'TagSet' to specify values for 'N':
    >> N[d] ^= 5;
    However, the value will not be stored in 'UpValues', but
    in 'NValues' (as for 'Set'):
    >> UpValues[d]
     = {}
    >> NValues[d]
     = {HoldPattern[N[d, MachinePrecision]] :> 5}
    >> e /: N[e] = 6;
    >> N[e]
     = 6.

    Values for 'N[$expr$]' must be associated with the head of $expr$:
    >> f /: N[e[f]] = 7;
     : Tag f not found or too deep for an assigned rule.

    You can use 'Condition':
    >> N[g[x_, y_], p_] := x + y * Pi /; x + y > 3
    >> SetAttributes[g, NHoldRest]
    >> N[g[1, 1]]
     = g[1., 1]
    >> N[g[2, 2]] // InputForm
     = 8.283185307179586

    The precision of the result is no higher than the precision of the input
    >> N[Exp[0.1], 100]
     = 1.10517
    >> % // Precision
     = MachinePrecision
    >> N[Exp[1/10], 100]
     = 1.105170918075647624811707826490246668224547194737518718792863289440967966747654302989143318970748654
    >> % // Precision
     = 100.
    >> N[Exp[1.0`20], 100]
     = 2.7182818284590452354
    >> % // Precision
     = 20.

    N can also accept an option "Method". This establishes what is the prefered underlying method to
    compute numerical values:
    >> N[F[Pi], 30, Method->"numpy"]
     = F[3.14159265358979300000000000000]
    >> N[F[Pi], 30, Method->"sympy"]
     = F[3.14159265358979323846264338328]
    #> p=N[Pi,100]
     = 3.141592653589793238462643383279502884197169399375105820974944592307816406286208998628034825342117068
    #> ToString[p]
     = 3.141592653589793238462643383279502884197169399375105820974944592307816406286208998628034825342117068

    #> N[1.012345678901234567890123, 20]
     = 1.0123456789012345679

    #> N[I, 30]
     = 1.00000000000000000000000000000 I

    #> N[1.012345678901234567890123, 50]
     = 1.01234567890123456789012
    #> % // Precision
     = 24.
    """

    options = {"Method": "Automatic"}

    messages = {
        "precbd": ("Requested precision `1` is not a " + "machine-sized real number."),
        "preclg": (
            "Requested precision `1` is larger than $MaxPrecision. "
            + "Using current $MaxPrecision of `2` instead. "
            + "$MaxPrecision = Infinity specifies that any precision "
            + "should be allowed."
        ),
        "precsm": (
            "Requested precision `1` is smaller than "
            + "$MinPrecision. Using current $MinPrecision of "
            + "`2` instead."
        ),
    }

    summary_text = "numerical evaluation to specified precision and accuracy"

    def apply_with_prec(self, expr, prec, evaluation, options=None):
        "N[expr_, prec_, OptionsPattern[%(name)s]]"

        # If options are passed, set the preference in evaluation, and call again
        # without options set.
        # This also prevents to store this as an nvalue (nvalues always have two leaves).
        preference = None
        # If a Method is passed, and the method is not either "Automatic" or
        # the last preferred method, according to evaluation._preferred_n_method,
        # set the new preference, reevaluate, and then remove the preference.
        if options:
            preference_queue = evaluation._preferred_n_method
            preference = self.get_option(
                options, "Method", evaluation
            ).get_string_value()
            if preference == "Automatic":
                preference = None
            if preference_queue and preference == preference_queue[-1]:
                preference = None

            if preference:
                preference_queue.append(preference)
                try:
                    result = self.apply_with_prec(expr, prec, evaluation)
                except Exception:
                    result = None
                preference_queue.pop()
                return result

        return apply_N(expr, evaluation, prec)

    def apply_N(self, expr, evaluation):
        """N[expr_]"""
        # TODO: Specialize for atoms
        return apply_N(expr, evaluation)


class NumericQ(Builtin):
    """
    <dl>
    <dt>'NumericQ[$expr$]'
        <dd>tests whether $expr$ represents a numeric quantity.
    </dl>

    >> NumericQ[2]
     = True
    >> NumericQ[Sqrt[Pi]]
     = True
    >> NumberQ[Sqrt[Pi]]
     = False
    """

    def apply(self, expr, evaluation):
        "NumericQ[expr_]"
        return SymbolTrue if expr.is_numeric(evaluation) else SymbolFalse


class Precision(Builtin):
    """
    <dl>
    <dt>'Precision[$expr$]'
        <dd>examines the number of significant digits of $expr$.
    </dl>
    This is rather a proof-of-concept than a full implementation.
    Precision of compound expression is not supported yet.
    >> Precision[1]
     = Infinity
    >> Precision[1/2]
     = Infinity
    >> Precision[0.5]
     = MachinePrecision

    #> Precision[0.0]
     = MachinePrecision
    #> Precision[0.000000000000000000000000000000000000]
     = 0.
    #> Precision[-0.0]
     = MachinePrecision
    #> Precision[-0.000000000000000000000000000000000000]
     = 0.

    #> 1.0000000000000000 // Precision
     = MachinePrecision
    #> 1.00000000000000000 // Precision
     = 17.

    #> 0.4 + 2.4 I // Precision
     = MachinePrecision
    #> Precision[2 + 3 I]
     = Infinity

    #> Precision["abc"]
     = Infinity
    """

    rules = {
        "Precision[z_?MachineNumberQ]": "MachinePrecision",
    }

    summary_text = "find the precision of a number"

    def apply(self, z, evaluation):
        "Precision[z_]"

        if not z.is_inexact():
            return Symbol("Infinity")
        elif z.to_sympy().is_zero:
            return Real(0)
        else:
            return Real(dps(z.get_precision()))


class Rationalize(Builtin):
    """
    <dl>
      <dt>'Rationalize[$x$]'
      <dd>converts a real number $x$ to a nearby rational number with small denominator.

      <dt>'Rationalize[$x$, $dx$]'
      <dd>finds the rational number lies within $dx$ of $x$.
    </dl>

    >> Rationalize[2.2]
    = 11 / 5

    For negative $x$, '-Rationalize[-$x$] == Rationalize[$x$]' which gives symmetric results:
    >> Rationalize[-11.5, 1]
    = -11

    Not all numbers can be well approximated.
    >> Rationalize[N[Pi]]
     = 3.14159

    Find the exact rational representation of 'N[Pi]'
    >> Rationalize[N[Pi], 0]
     = 245850922 / 78256779

    #> Rationalize[N[Pi] + 0.8 I, x]
     : Tolerance specification x must be a non-negative number.
     = Rationalize[3.14159 + 0.8 I, x]

    #> Rationalize[N[Pi] + 0.8 I, -1]
     : Tolerance specification -1 must be a non-negative number.
     = Rationalize[3.14159 + 0.8 I, -1]

    #> Rationalize[x, y]
     : Tolerance specification y must be a non-negative number.
     = Rationalize[x, y]
    """

    messages = {
        "tolnn": "Tolerance specification `1` must be a non-negative number.",
    }

    rules = {
        "Rationalize[z_Complex]": "Rationalize[Re[z]] + I Rationalize[Im[z]]",
        "Rationalize[z_Complex, dx_?Internal`RealValuedNumberQ]/;dx >= 0": "Rationalize[Re[z], dx] + I Rationalize[Im[z], dx]",
    }

    summary_text = "find a rational approximation"

    def apply(self, x, evaluation):
        "Rationalize[x_]"

        py_x = x.to_sympy()
        if py_x is None or (not py_x.is_number) or (not py_x.is_real):
            return x

        # For negative x, MMA treads Rationalize[x] as -Rationalize[-x].
        # Whether this is an implementation choice or not, it has been
        # expressed that having this give symmetric results for +/-
        # is nice.
        # See https://mathematica.stackexchange.com/questions/253637/how-to-think-about-the-answer-to-rationlize-11-5-1
        if py_x.is_positive:
            return from_sympy(self.find_approximant(py_x))
        else:
            return -from_sympy(self.find_approximant(-py_x))

    @staticmethod
    def find_approximant(x):
        c = 1e-4
        it = sympy.ntheory.continued_fraction_convergents(
            sympy.ntheory.continued_fraction_iterator(x)
        )
        for i in it:
            p, q = i.as_numer_denom()
            tol = c / q ** 2
            if abs(i - x) <= tol:
                return i
            if tol < machine_epsilon:
                break
        return x

    @staticmethod
    def find_exact(x):
        p, q = x.as_numer_denom()
        it = sympy.ntheory.continued_fraction_convergents(
            sympy.ntheory.continued_fraction_iterator(x)
        )
        for i in it:
            p, q = i.as_numer_denom()
            if abs(x - i) < machine_epsilon:
                return i

    def apply_dx(self, x, dx, evaluation):
        "Rationalize[x_, dx_]"
        py_x = x.to_sympy()
        if py_x is None:
            return x
        py_dx = dx.to_sympy()
        if (
            py_dx is None
            or (not py_dx.is_number)
            or (not py_dx.is_real)
            or py_dx.is_negative
        ):
            return evaluation.message("Rationalize", "tolnn", dx)
        elif py_dx == 0:
            return from_sympy(self.find_exact(py_x))

        # For negative x, MMA treads Rationalize[x] as -Rationalize[-x].
        # Whether this is an implementation choice or not, it has been
        # expressed that having this give symmetric results for +/-
        # is nice.
        # See https://mathematica.stackexchange.com/questions/253637/how-to-think-about-the-answer-to-rationlize-11-5-1
        if py_x.is_positive:
            a = self.approx_interval_continued_fraction(py_x - py_dx, py_x + py_dx)
            sym_x = sympy.ntheory.continued_fraction_reduce(a)
        else:
            a = self.approx_interval_continued_fraction(-py_x - py_dx, -py_x + py_dx)
            sym_x = -sympy.ntheory.continued_fraction_reduce(a)

        return Integer(sym_x) if sym_x.is_integer else Rational(sym_x)

    @staticmethod
    def approx_interval_continued_fraction(xmin, xmax):
        result = []
        a_gen = sympy.ntheory.continued_fraction_iterator(xmin)
        b_gen = sympy.ntheory.continued_fraction_iterator(xmax)
        while True:
            a, b = next(a_gen), next(b_gen)
            if a == b:
                result.append(a)
            else:
                result.append(min(a, b) + 1)
                break
        return result


class RealValuedNumericQ(Builtin):
    # No docstring since this is internal and it will mess up documentation.
    # FIXME: Perhaps in future we will have a more explicite way to indicate not
    # to add something to the docs.
    context = "Internal`"

    rules = {
        "Internal`RealValuedNumericQ[x_]": "Head[N[x]] === Real",
    }


class RealValuedNumberQ(Builtin):
    # No docstring since this is internal and it will mess up documentation.
    # FIXME: Perhaps in future we will have a more explicite way to indicate not
    # to add something to the docs.
    context = "Internal`"

    rules = {
        "Internal`RealValuedNumberQ[x_Real]": "True",
        "Internal`RealValuedNumberQ[x_Integer]": "True",
        "Internal`RealValuedNumberQ[x_Rational]": "True",
        "Internal`RealValuedNumberQ[x_]": "False",
    }


class Round(Builtin):
    """
    <dl>
    <dt>'Round[$expr$]'
        <dd>rounds $expr$ to the nearest integer.
    <dt>'Round[$expr$, $k$]'
        <dd>rounds $expr$ to the closest multiple of $k$.
    </dl>

    >> Round[10.6]
     = 11
    >> Round[0.06, 0.1]
     = 0.1
    >> Round[0.04, 0.1]
     = 0.

    Constants can be rounded too
    >> Round[Pi, .5]
     = 3.
    >> Round[Pi^2]
     = 10

    Round to exact value
    >> Round[2.6, 1/3]
     = 8 / 3
    >> Round[10, Pi]
     = 3 Pi

    Round complex numbers
    >> Round[6/(2 + 3 I)]
     = 1 - I
    >> Round[1 + 2 I, 2 I]
     = 2 I

    Round Negative numbers too
    >> Round[-1.4]
     = -1

    Expressions other than numbers remain unevaluated:
    >> Round[x]
     = Round[x]
    >> Round[1.5, k]
     = Round[1.5, k]
    """

    attributes = listable | numeric_function | protected

    rules = {
        "Round[expr_?NumericQ]": "Round[Re[expr], 1] + I * Round[Im[expr], 1]",
        "Round[expr_Complex, k_?RealNumberQ]": (
            "Round[Re[expr], k] + I * Round[Im[expr], k]"
        ),
    }

    def apply(self, expr, k, evaluation):
        "Round[expr_?NumericQ, k_?NumericQ]"

        n = Expression("Divide", expr, k).round_to_float(
            evaluation, permit_complex=True
        )
        if n is None:
            return
        elif isinstance(n, complex):
            n = round(n.real)
        else:
            n = round(n)
        n = int(n)
        return Expression("Times", Integer(n), k)


class RealDigits(Builtin):
    """
    <dl>
      <dt>'RealDigits[$n$]'
      <dd>returns the decimal representation of the real number $n$ as list of digits, together with the number of digits that are to the left of the decimal point.

      <dt>'RealDigits[$n$, $b$]'
      <dd>returns a list of base_$b$ representation of the real number $n$.

      <dt>'RealDigits[$n$, $b$, $len$]'
      <dd>returns a list of $len$ digits.

      <dt>'RealDigits[$n$, $b$, $len$, $p$]'
      <dd>return $len$ digits starting with the coefficient of $b$^$p$
    </dl>

    Return the list of digits and exponent:
    >> RealDigits[123.55555]
     = {{1, 2, 3, 5, 5, 5, 5, 5, 0, 0, 0, 0, 0, 0, 0, 0}, 3}

    Return an explicit recurring decimal form:
    >> RealDigits[19 / 7]
     = {{2, {7, 1, 4, 2, 8, 5}}, 1}

    The 10000th digit of  is an 8:
    >> RealDigits[Pi, 10, 1, -10000]
    = {{8}, -9999}

    20 digits starting with the coefficient of 10^-5:
    >> RealDigits[Pi, 10, 20, -5]
     = {{9, 2, 6, 5, 3, 5, 8, 9, 7, 9, 3, 2, 3, 8, 4, 6, 2, 6, 4, 3}, -4}

    RealDigits gives Indeterminate if more digits than the precision are requested:
    >> RealDigits[123.45, 10, 18]
     = {{1, 2, 3, 4, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, Indeterminate, Indeterminate}, 3}

    #> RealDigits[-1.25, -1]
     : Base -1 is not a real number greater than 1.
     = RealDigits[-1.25, -1]

    Return 25 digits of in base 10:
    >> RealDigits[Pi, 10, 25]
     = {{3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9, 3, 2, 3, 8, 4, 6, 2, 6, 4, 3}, 1}

    #> RealDigits[-Pi]
     : The number of digits to return cannot be determined.
     = RealDigits[-Pi]

    #> RealDigits[I, 7]
     : The value I is not a real number.
    = RealDigits[I, 7]

    #> RealDigits[Pi]
     : The number of digits to return cannot be determined.
     = RealDigits[Pi]

    #> RealDigits[3 + 4 I]
     : The value 3 + 4 I is not a real number.
     = RealDigits[3 + 4 I]


    #> RealDigits[3.14, 10, 1.5]
     : Non-negative machine-sized integer expected at position 3 in RealDigits[3.14, 10, 1.5].
     = RealDigits[3.14, 10, 1.5]

    #> RealDigits[3.14, 10, 1, 1.5]
     : Machine-sized integer expected at position 4 in RealDigits[3.14, 10, 1, 1.5].
     = RealDigits[3.14, 10, 1, 1.5]

    """

    attributes = listable | protected

    messages = {
        "realx": "The value `1` is not a real number.",
        "ndig": "The number of digits to return cannot be determined.",
        "rbase": "Base `1` is not a real number greater than 1.",
        "intnm": "Non-negative machine-sized integer expected at position 3 in `1`.",
        "intm": "Machine-sized integer expected at position 4 in `1`.",
    }

    summary_text = "digits of a real number"

    def apply_complex(self, n, var, evaluation):
        "%(name)s[n_Complex, var___]"
        return evaluation.message("RealDigits", "realx", n)

    def apply_rational_with_base(self, n, b, evaluation):
        "%(name)s[n_Rational, b_Integer]"
        # expr = Expression("RealDigits", n)
        py_n = abs(n.value)
        py_b = b.get_int_value()
        if check_finite_decimal(n.denominator().get_int_value()) and not py_b % 2:
            return self.apply_with_base(n, b, evaluation)
        else:
            exp = int(mpmath.ceil(mpmath.log(py_n, py_b)))
            (head, tails) = convert_repeating_decimal(
                py_n.as_numer_denom()[0], py_n.as_numer_denom()[1], py_b
            )

            leaves = []
            for x in head:
                if x != "0":
                    leaves.append(Integer(int(x)))
            leaves.append(from_python(tails))
            list_str = Expression(SymbolList, *leaves)
        return Expression(SymbolList, list_str, exp)

    def apply_rational_without_base(self, n, evaluation):
        "%(name)s[n_Rational]"

        return self.apply_rational_with_base(n, Integer(10), evaluation)

    def apply(self, n, evaluation):
        "%(name)s[n_]"

        # Handling the testcases that throw the error message and return the ouput that doesn't include `base` argument
        if isinstance(n, Symbol) and n.name.startswith("System`"):
            return evaluation.message("RealDigits", "ndig", n)

        if n.is_numeric(evaluation):
            return self.apply_with_base(n, from_python(10), evaluation)

    def apply_with_base(self, n, b, evaluation, nr_elements=None, pos=None):
        "%(name)s[n_?NumericQ, b_Integer]"

        expr = Expression("RealDigits", n)
        rational_no = (
            True if isinstance(n, Rational) else False
        )  # it is used for checking whether the input n is a rational or not
        py_b = b.get_int_value()
        if isinstance(n, (Expression, Symbol, Rational)):
            pos_len = abs(pos) + 1 if pos is not None and pos < 0 else 1
            if nr_elements is not None:
                n = Expression(
                    "N", n, int(mpmath.log(py_b ** (nr_elements + pos_len), 10)) + 1
                ).evaluate(evaluation)
            else:
                if rational_no:
                    n = apply_N(n, evaluation)
                else:
                    return evaluation.message("RealDigits", "ndig", expr)
        py_n = abs(n.value)

        if not py_b > 1:
            return evaluation.message("RealDigits", "rbase", py_b)

        if isinstance(py_n, complex):
            return evaluation.message("RealDigits", "realx", expr)

        if isinstance(n, Integer):
            display_len = (
                int(mpmath.floor(mpmath.log(py_n, py_b)))
                if py_n != 0 and py_n != 1
                else 1
            )
        else:
            display_len = int(
                Expression(
                    "N",
                    Expression(
                        "Round",
                        Expression(
                            "Divide",
                            Expression("Precision", py_n),
                            Expression("Log", 10, py_b),
                        ),
                    ),
                )
                .evaluate(evaluation)
                .to_python()
            )

        exp = log_n_b(py_n, py_b)

        if py_n == 0 and nr_elements is not None:
            exp = 0

        digits = []
        if not py_b == 10:
            digits = convert_float_base(py_n, py_b, display_len - exp)
            # truncate all the leading 0's
            i = 0
            while digits and digits[i] == 0:
                i += 1
            digits = digits[i:]

            if not isinstance(n, Integer):
                if len(digits) > display_len:
                    digits = digits[: display_len - 1]
        else:
            # drop any leading zeroes
            for x in str(py_n):
                if x != "." and (digits or x != "0"):
                    digits.append(x)

        if pos is not None:
            temp = exp
            exp = pos + 1
            move = temp - 1 - pos
            if move <= 0:
                digits = [0] * abs(move) + digits
            else:
                digits = digits[abs(move) :]
                display_len = display_len - move

        leaves = []
        for x in digits:
            if x == "e" or x == "E":
                break
            # Convert to Mathics' list format
            leaves.append(Integer(int(x)))

        if not rational_no:
            while len(leaves) < display_len:
                leaves.append(Integer0)

        if nr_elements is not None:
            # display_len == nr_elements
            if len(leaves) >= nr_elements:
                # Truncate, preserving the digits on the right
                leaves = leaves[:nr_elements]
            else:
                if isinstance(n, Integer):
                    while len(leaves) < nr_elements:
                        leaves.append(Integer0)
                else:
                    # Adding Indeterminate if the length is greater than the precision
                    while len(leaves) < nr_elements:
                        leaves.append(from_python(Symbol("Indeterminate")))
        list_str = Expression(SymbolList, *leaves)
        return Expression(SymbolList, list_str, exp)

    def apply_with_base_and_length(self, n, b, length, evaluation, pos=None):
        "%(name)s[n_?NumericQ, b_Integer, length_]"
        leaves = []
        if pos is not None:
            leaves.append(from_python(pos))
        expr = Expression("RealDigits", n, b, length, *leaves)
        if not (isinstance(length, Integer) and length.get_int_value() >= 0):
            return evaluation.message("RealDigits", "intnm", expr)

        return self.apply_with_base(
            n, b, evaluation, nr_elements=length.get_int_value(), pos=pos
        )

    def apply_with_base_length_and_precision(self, n, b, length, p, evaluation):
        "%(name)s[n_?NumericQ, b_Integer, length_, p_]"
        if not isinstance(p, Integer):
            return evaluation.message(
                "RealDigits", "intm", Expression("RealDigits", n, b, length, p)
            )

        return self.apply_with_base_and_length(
            n, b, length, evaluation, pos=p.get_int_value()
        )


class _ZLibHash:  # make zlib hashes behave as if they were from hashlib
    def __init__(self, fn):
        self._bytes = b""
        self._fn = fn

    def update(self, bytes):
        self._bytes += bytes

    def hexdigest(self):
        return format(self._fn(self._bytes), "x")


class Hash(Builtin):
    """
    <dl>
    <dt>'Hash[$expr$]'
      <dd>returns an integer hash for the given $expr$.
    <dt>'Hash[$expr$, $type$]'
      <dd>returns an integer hash of the specified $type$ for the given $expr$.</dd>
      <dd>The types supported are "MD5", "Adler32", "CRC32", "SHA", "SHA224", "SHA256", "SHA384", and "SHA512".</dd>
    <dt>'Hash[$expr$, $type$, $format$]'
      <dd>Returns the hash in the specified format.</dd>
    </dl>

    > Hash["The Adventures of Huckleberry Finn"]
    = 213425047836523694663619736686226550816

    > Hash["The Adventures of Huckleberry Finn", "SHA256"]
    = 95092649594590384288057183408609254918934351811669818342876362244564858646638

    > Hash[1/3]
    = 56073172797010645108327809727054836008

    > Hash[{a, b, {c, {d, e, f}}}]
    = 135682164776235407777080772547528225284

    > Hash[SomeHead[3.1415]]
    = 58042316473471877315442015469706095084

    >> Hash[{a, b, c}, "xyzstr"]
     = Hash[{a, b, c}, xyzstr, Integer]
    """

    rules = {
        "Hash[expr_]": 'Hash[expr, "MD5", "Integer"]',
        "Hash[expr_, type_String]": 'Hash[expr, type, "Integer"]',
    }

    attributes = protected | read_protected

    # FIXME md2
    _supported_hashes = {
        "Adler32": lambda: _ZLibHash(zlib.adler32),
        "CRC32": lambda: _ZLibHash(zlib.crc32),
        "MD5": hashlib.md5,
        "SHA": hashlib.sha1,
        "SHA224": hashlib.sha224,
        "SHA256": hashlib.sha256,
        "SHA384": hashlib.sha384,
        "SHA512": hashlib.sha512,
    }

    @staticmethod
    def compute(user_hash, py_hashtype, py_format):
        hash_func = Hash._supported_hashes.get(py_hashtype)
        if hash_func is None:  # unknown hash function?
            return  # in order to return original Expression
        h = hash_func()
        user_hash(h.update)
        res = h.hexdigest()
        if py_format in ("HexString", "HexStringLittleEndian"):
            return String(res)
        res = int(res, 16)
        if py_format == "DecimalString":
            return String(str(res))
        elif py_format == "ByteArray":
            return from_python(bytearray(res))
        return Integer(res)

    def apply(self, expr, hashtype, outformat, evaluation):
        "Hash[expr_, hashtype_String, outformat_String]"
        return Hash.compute(
            expr.user_hash, hashtype.get_string_value(), outformat.get_string_value()
        )


class TypeEscalation(Exception):
    def __init__(self, mode):
        self.mode = mode