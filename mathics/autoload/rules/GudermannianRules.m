(* Adapted from symja_android_library/symja_android_library/rules/QuantileRules.m *)
(* This has been added as a Mathics Builtin in mathics.builtin.numbers.hyperbolic
Begin["System`"]

Gudermannian::usage = "gives the Gudermannian function";
Gudermannian[Undefined]=Undefined;
Gudermannian[0]=0;
Gudermannian[2*Pi*I]=0;
Gudermannian[6/4*Pi*I]=DirectedInfinity[-I];
Gudermannian[Infinity]=Pi/2;
Gudermannian[-Infinity]=-Pi/2;
Gudermannian[ComplexInfinity]=Indeterminate;
Gudermannian[z_]=2 ArcTan[Tanh[z / 2]];
 *)

(* Commented out because ":=" might not work properly...

Gudermannian[z_] := Piecewise[{{1/2*[Pi - 4*ArcCot[E^z]], Re[z]>0||(Re[z]==0&&Im[z]>=0 )}}, 1/2 (-Pi + 4 ArcTan[E^z])];
D[Gudermannian[f_],x_?NotListQ] := Sech[f] D[f,x];
Derivative[1][InverseGudermannian] := Sec[#] &;
Derivative[1][Gudermannian] := Sech[#] &;

End[]
*)
