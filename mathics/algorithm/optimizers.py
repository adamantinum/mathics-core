# -*- coding: utf-8 -*-


from mathics.core.expression import Expression
from mathics.core.atoms import (
    String,
    Integer,
    Integer1,
    Integer2,
    Integer3,
    Integer10,
    Number,
    Real,
    from_python,
)

from mathics.core.symbols import (
    SymbolTrue,
)

from mathics.core.systemsymbols import (
    SymbolAutomatic,
    SymbolInfinity,
    SymbolLess,
    SymbolLessEqual,
    SymbolLog,
    SymbolNone,
)

from mathics.builtin.scoping import dynamic_scoping
from mathics.builtin.numeric import apply_N


def find_minimum_newton1d(f, x0, x, opts, evaluation) -> (Number, bool):
    is_find_maximum = opts.get("_isfindmaximum", False)
    symbol_name = "FindMaximum" if is_find_maximum else "FindMinimum"
    if is_find_maximum:
        f = -f
        # TODO: revert jacobian if given...

    x_name = x.name
    maxit = opts["System`MaxIterations"]
    step_monitor = opts.get("System`StepMonitor", None)
    if step_monitor is SymbolNone:
        step_monitor = None
    evaluation_monitor = opts.get("System`EvaluationMonitor", None)
    if evaluation_monitor is SymbolNone:
        evaluation_monitor = None

    if maxit is SymbolAutomatic:
        maxit = 100
    else:
        maxit = maxit.evaluate(evaluation).get_int_value()

    acc_goal, prec_goal = get_accuracy_and_prec(opts, evaluation)
    curr_val = apply_N(f.replace_vars({x_name: x0}), evaluation)

    # build the quadratic form:
    eps = determine_epsilon(x0, opts, evaluation)
    if not isinstance(curr_val, Number):
        evaluation.message(symbol_name, "nnum", x, x0)
        if is_find_maximum:
            return -x0, False
        else:
            return x0, False
    d1 = dynamic_scoping(
        lambda ev: Expression("D", f, x).evaluate(ev), {x_name: None}, evaluation
    )
    val_d1 = apply_N(d1.replace_vars({x_name: x0}), evaluation)
    if not isinstance(val_d1, Number):
        d1 = None
        d2 = None
        f2val = apply_N(f.replace_vars({x_name: x0 + eps}), evaluation)
        f1val = apply_N(f.replace_vars({x_name: x0 - eps}), evaluation)
        val_d1 = apply_N((f2val - f1val) / (Integer2 * eps), evaluation)
        val_d2 = apply_N(
            (f2val + f1val - Integer2 * curr_val) / (eps ** Integer2), evaluation
        )
    else:
        d2 = dynamic_scoping(
            lambda ev: Expression("D", d1, x).evaluate(ev), {x_name: None}, evaluation
        )
        val_d2 = apply_N(d2.replace_vars({x_name: x0}), evaluation)
        if not isinstance(val_d2, Number):
            d2 = None
            df2val = apply_N(d1.replace_vars({x_name: x0 + eps}), evaluation)
            df1val = apply_N(d1.replace_vars({x_name: x0 - eps}), evaluation)
            val_d2 = (df2val - df1val) / (Integer2 * eps)

    def reset_values(x0):
        x_try = [
            apply_N(x0 / Integer3, evaluation),
            apply_N(x0 * Integer2, evaluation),
            apply_N(x0 - offset / Integer2, evaluation),
        ]
        vals = [(u, apply_N(f.replace_vars({x_name: u}), evaluation)) for u in x_try]
        vals = [v for v in vals if isinstance(v[1], Number)]
        v0 = vals[0]
        for v in vals:
            if Expression(SymbolLess, v[1], v0[1]).evaluate(evaluation) is SymbolTrue:
                v0 = v
        return v0

    def reevaluate_coeffs():
        """reevaluates val_d1 and val_d2"""
        if d1:
            val_d1 = apply_N(d1.replace_vars({x_name: x0}), evaluation)
            if d2:
                val_d2 = apply_N(d2.replace_vars({x_name: x0}), evaluation)
            else:
                df2val = apply_N(d1.replace_vars({x_name: x0 + eps}), evaluation)
                df1val = apply_N(d1.replace_vars({x_name: x0 - eps}), evaluation)
                val_d2 = (df2val - df1val) / (Integer2 * eps)
        else:
            f2val = apply_N(f.replace_vars({x_name: x0 + eps}), evaluation)
            f1val = apply_N(f.replace_vars({x_name: x0 - eps}), evaluation)
            val_d1 = apply_N((f2val - f1val) / (Integer2 * eps), evaluation)
            val_d2 = apply_N(
                (f2val + f1val - Integer2 * curr_val) / (eps ** Integer2), evaluation
            )
        return (val_d1, val_d2)

    # Main loop
    count = 0

    while count < maxit:
        if step_monitor:
            step_monitor.replace_vars({x_name: x0}).evaluate(evaluation)

        if val_d1.is_zero:
            if is_find_maximum:
                evaluation.message(
                    symbol_name, "fmgz", String("maximum"), String("minimum")
                )
            else:
                evaluation.message(
                    symbol_name, "fmgz", String("minimum"), String("maximum")
                )

            if is_find_maximum:
                return (x0, -curr_val), True
            else:
                return (x0, curr_val), True
        if val_d2.is_zero:
            val_d2 = Integer1

        offset = apply_N(val_d1 / abs(val_d2), evaluation)
        x1 = apply_N(x0 - offset, evaluation)
        new_val = apply_N(f.replace_vars({x_name: x1}), evaluation)
        if (
            Expression(SymbolLessEqual, new_val, curr_val).evaluate(evaluation)
            is SymbolTrue
        ):
            if is_zero(offset, acc_goal, prec_goal, evaluation):
                if is_find_maximum:
                    return (x1, -curr_val), True
                else:
                    return (x1, curr_val), True
            x0 = x1
            curr_val = new_val
        else:
            if is_zero(offset / Integer2, acc_goal, prec_goal, evaluation):
                if is_find_maximum:
                    return (x0, -curr_val), True
                else:
                    return (x0, curr_val), True
            x0, curr_val = reset_values(x0)
        val_d1, val_d2 = reevaluate_coeffs()
        count = count + 1
    else:
        evaluation.message(symbol_name, "maxiter")
    if is_find_maximum:
        return (x0, -curr_val), False
    else:
        return (x0, curr_val), False


def find_root_secant(f, x0, x, opts, evaluation) -> (Number, bool):
    region = opts.get("$$Region", None)
    if not type(region) is list:
        if x0.is_zero:
            region = (Real(-1), Real(1))
        else:
            xmax = 2 * x0.to_python()
            xmin = -2 * x0.to_python()
            if xmin > xmax:
                region = (Real(xmax), Real(xmin))
            else:
                region = (Real(xmin), Real(xmax))

    maxit = opts["System`MaxIterations"]
    x_name = x.get_name()
    if maxit is SymbolAutomatic:
        maxit = 100
    else:
        maxit = maxit.evaluate(evaluation).get_int_value()

    x0 = from_python(region[0])
    x1 = from_python(region[1])
    f0 = dynamic_scoping(lambda ev: f.evaluate(evaluation), {x_name: x0}, evaluation)
    f1 = dynamic_scoping(lambda ev: f.evaluate(evaluation), {x_name: x1}, evaluation)
    if not isinstance(f0, Number):
        return x0, False
    if not isinstance(f1, Number):
        return x0, False
    f0 = f0.to_python(n_evaluation=True)
    f1 = f1.to_python(n_evaluation=True)
    count = 0
    while count < maxit:
        if f0 == f1:
            x1 = Expression(
                "Plus",
                x0,
                Expression(
                    "Times",
                    Real(0.75),
                    Expression("Plus", x1, Expression("Times", Integer(-1), x0)),
                ),
            )
            x1 = x1.evaluate(evaluation)
            f1 = dynamic_scoping(
                lambda ev: f.evaluate(evaluation), {x_name: x1}, evaluation
            )
            if not isinstance(f1, Number):
                return x0, False
            f1 = f1.to_python(n_evaluation=True)
            continue

        inv_deltaf = from_python(1.0 / (f1 - f0))
        num = Expression(
            "Plus",
            Expression("Times", x0, f1),
            Expression("Times", x1, f0, Integer(-1)),
        )
        x2 = Expression("Times", num, inv_deltaf)
        x2 = x2.evaluate(evaluation)
        f2 = dynamic_scoping(
            lambda ev: f.evaluate(evaluation), {x_name: x2}, evaluation
        )
        if not isinstance(f2, Number):
            return x0, False
        f2 = f2.to_python(n_evaluation=True)
        f1, f0 = f2, f1
        x1, x0 = x2, x1
        if x1 == x0 or abs(f2) == 0:
            break
        count = count + 1
    else:
        evaluation.message("FindRoot", "maxiter")
        return x0, False
    return x0, True


def find_root_newton(f, x0, x, opts, evaluation) -> (Number, bool):
    """
    Look for a root of a f: R->R using the Newton's method.
    """
    absf = abs(f)
    df = opts["System`Jacobian"]
    maxit = opts["System`MaxIterations"]
    x_name = x.get_name()
    if maxit is SymbolAutomatic:
        maxit = 100
    else:
        maxit = maxit.evaluate(evaluation).get_int_value()

    acc_goal, prec_goal = get_accuracy_and_prec(opts, evaluation)

    step_monitor = opts.get("System`StepMonitor", None)
    if step_monitor is SymbolNone:
        step_monitor = None
    evaluation_monitor = opts.get("System`EvaluationMonitor", None)
    if evaluation_monitor is SymbolNone:
        evaluation_monitor = None

    def decreasing(val1, val2):
        """
        Check if val2 has a smaller absolute value than val1
        """
        if not (val1.is_numeric() and val2.is_numeric()):
            return False
        if val2.is_zero:
            return True
        res = apply_N(Expression(SymbolLog, abs(val2 / val1)), evaluation)
        if not res.is_numeric():
            return False
        return res.to_python() < 0

    def new_seed():
        """
        looks for a new starting point, based on how close we are from the target.
        """
        x1 = apply_N(Integer2 * x0, evaluation)
        x2 = apply_N(x0 / Integer3, evaluation)
        x3 = apply_N(x0 - minus / Integer2, evaluation)
        x4 = apply_N(x0 + minus / Integer3, evaluation)
        absf1 = apply_N(absf.replace_vars({x_name: x1}), evaluation)
        absf2 = apply_N(absf.replace_vars({x_name: x2}), evaluation)
        absf3 = apply_N(absf.replace_vars({x_name: x3}), evaluation)
        absf4 = apply_N(absf.replace_vars({x_name: x4}), evaluation)
        if decreasing(absf1, absf2):
            x1, absf1 = x2, absf2
        if decreasing(absf1, absf3):
            x1, absf1 = x3, absf3
        if decreasing(absf1, absf4):
            x1, absf1 = x4, absf4
        return x1, absf1

    def sub(evaluation):
        d_value = apply_N(df, evaluation)
        if d_value == Integer(0):
            return None
        result = apply_N(f / d_value, evaluation)
        if evaluation_monitor:
            dynamic_scoping(
                lambda ev: evaluation_monitor.evaluate(ev), {x_name: x0}, evaluation
            )
        return result

    currval = absf.replace_vars({x_name: x0}).evaluate(evaluation)
    count = 0
    while count < maxit:
        if step_monitor:
            dynamic_scoping(
                lambda ev: step_monitor.evaluate(ev), {x_name: x0}, evaluation
            )
        minus = dynamic_scoping(sub, {x_name: x0}, evaluation)
        if minus is None:
            evaluation.message("FindRoot", "dsing", x, x0)
            return x0, False
        x1 = Expression("Plus", x0, Expression("Times", Integer(-1), minus)).evaluate(
            evaluation
        )
        if not isinstance(x1, Number):
            evaluation.message("FindRoot", "nnum", x, x0)
            return x0, False

        # Check convergency:
        new_currval = absf.replace_vars({x_name: x1}).evaluate(evaluation)
        if is_zero(new_currval, acc_goal, prec_goal, evaluation):
            return x1, True

        # This step tries to ensure that the new step goes forward to the convergency.
        # If not, tries to restart in a another point closer to x0 than x1.
        if decreasing(new_currval, currval):
            x0, currval = new_seed()
            count = count + 1
            continue
        else:
            currval = new_currval
            x0 = apply_N(x1, evaluation)
            # N required due to bug in sympy arithmetic
            count += 1
    else:
        evaluation.message("FindRoot", "maxiter")
    return x0, True


native_local_optimizer_methods = {
    "Automatic": find_minimum_newton1d,
    "newton": find_minimum_newton1d,
}

native_findroot_methods = {
    "Automatic": find_root_newton,
    "newton": find_root_newton,
    "secant": find_root_secant,
}


def is_zero(val, acc_goal, prec_goal, evaluation):
    """
    Check if val is zero upto the precision and accuracy goals
    """
    if not isinstance(val, Number):
        val = apply_N(val, evaluation)
    if not val.is_numeric():
        return False
    if val.is_zero:
        return True
    if acc_goal:
        if prec_goal:
            eps = apply_N(
                Expression(
                    SymbolLog,
                    Integer10 ** (-acc_goal) / abs(val) + Integer10 ** (-prec_goal),
                ),
                evaluation,
            )
        else:
            eps = apply_N(
                Expression(SymbolLog, Integer10 ** (-acc_goal) / abs(val)),
                evaluation,
            )
        if isinstance(eps, Number):
            return eps.to_python() > 0
    return False


def get_accuracy_and_prec(opts: dict, evaluation: "Evaluation"):
    """
    Looks at an opts dictionary and tries to determine the numeric values of
    Accuracy and Precision goals. If not available, returns None.
    """
    acc_goal = opts.get("System`AccuracyGoal", None)
    if acc_goal:
        acc_goal = apply_N(acc_goal, evaluation)
        if acc_goal is SymbolAutomatic:
            acc_goal = Real(12.0)
        elif acc_goal is SymbolInfinity:
            acc_goal = None
        elif not isinstance(acc_goal, Number):
            acc_goal = None

    prec_goal = opts.get("System`PrecisionGoal", None)
    if prec_goal:
        prec_goal = apply_N(prec_goal, evaluation)
        if prec_goal is SymbolAutomatic:
            prec_goal = Real(12.0)
        elif prec_goal is SymbolInfinity:
            prec_goal = None
        elif not isinstance(prec_goal, Number):
            prec_goal = None
    return acc_goal, prec_goal


def determine_epsilon(x0, options, evaluation):
    """Determine epsilon  from a reference value, and from the accuracy and the precision goals"""
    acc_goal, prec_goal = get_accuracy_and_prec(options, evaluation)
    if acc_goal:
        if prec_goal:
            eps = apply_N(
                Integer10 ** (-acc_goal) + abs(x0) * Integer10 ** (-prec_goal),
                evaluation,
            )
        else:
            eps = apply_N(Integer10 ** (-acc_goal), evaluation)
    else:
        if prec_goal:
            eps = apply_N(abs(x0) * Integer10 ** (-prec_goal), evaluation)
        else:
            eps = Real(1e-10)
    return eps