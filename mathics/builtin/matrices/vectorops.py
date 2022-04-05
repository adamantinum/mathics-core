# -*- coding: utf-8 -*-

"""
Operations on Vectors

Methods for manipulating Vectors
"""

from mathics.builtin.base import Builtin
from mathics.core.expression import Expression
from mathics.core.symbols import Symbol, SymbolList


class Projection(Builtin):
    """
    <dl>
        <dt>'Projection[$a$, $b$]'
        <dd>gives the projection of vector $a$ on vector $b$
    </dl>
    """

    summary_text = "gives the projection of two vectors"

    rules = {
            "Projection[a_List, b_List]": "Projection[a, b, Dot]"
        }

    def apply(self, e1, e2, inner, evaluation):
        "Projection[e1_List, e2_List, inner_Symbol]"

        dot1 = Expression(inner, e1.elements, e2.elements)
        dot2 = Expression(inner, e2.elements, e2.elements)
        
        return Expression("Times", Expression("Divide", dot1, dot2), e2.elements)


class Orthogonalize(Builtin):
    """
    <dl>
        <dt>'Orthogonalize[{$a$, $b$, $c$}]
        <dd>
    </dl>
    """

    options = {
            "Method": "GramSchmidt",
    }

    rules = {
            "Orthogonalize[expr_List]": "Orthogonalize[expr, Dot]"
    }
    
    summary_text = "gives an orthonormal basis for a given vector set"

    def apply(self, expr, inner, evaluation, options={}):
        "Orthogonalize[expr_List, inner_Symbol, OptionsPattern[%(name)s]]"
        
        def gram_schmidt(expr, inner):
            basis = Expression("List")
            for count, value in enumerate(expr.elements):
                current_basis = value
                i = 0
                while i < count:
                    proj = Expression("Projection", value, expr.elements[i], inner)
                    current_basis = Expression("Subtract", current_basis, proj)
                    i += 1
            
                current_basis = Expression("Divide", current_basis, Expression("Norm", current_basis))
                basis = Expression("Append", basis, current_basis)
            return basis
        

        method = self.get_option(options, "Method", evaluation)
        
        if method.get_string_value() == "GramSchmidt":
            return gram_schmidt(expr, inner)
        else:
            return gram_schmidt(expr, inner)
