// Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
// SPDX-License-Identifier: Apache-2.0

// Evaluate rendered admission rules against allowed requests and bypass attempts.
package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/google/cel-go/cel"
	"github.com/google/cel-go/common/types"
)

type check struct {
	Name        string
	Matches     []string
	Validations []string
	Values      map[string]interface{}
	Allowed     bool
}

func main() {
	var checks []check
	if err := json.NewDecoder(os.Stdin).Decode(&checks); err != nil {
		panic(err)
	}
	env, err := cel.NewEnv(cel.Variable("object", cel.DynType),
		cel.Variable("oldObject", cel.DynType), cel.Variable("request", cel.DynType),
		cel.Variable("params", cel.DynType))
	if err != nil {
		panic(err)
	}
	evaluate := func(expression string, values map[string]interface{}) bool {
		ast, issues := env.Compile(expression)
		if issues.Err() != nil {
			panic(issues.Err())
		}
		program, err := env.Program(ast)
		if err != nil {
			panic(err)
		}
		result, _, err := program.Eval(values)
		if err != nil {
			panic(fmt.Sprintf("%s: %v", expression, err))
		}
		return result == types.True
	}
	for _, c := range checks {
		matched, allowed := true, true
		for _, expression := range c.Matches {
			matched = matched && evaluate(expression, c.Values)
		}
		if matched {
			for _, expression := range c.Validations {
				allowed = evaluate(expression, c.Values) && allowed
			}
		}
		if allowed != c.Allowed {
			panic(fmt.Sprintf("%s: allowed=%t, expected %t", c.Name, allowed, c.Allowed))
		}
	}
	fmt.Printf("PASS %d admission requests and bypass checks\n", len(checks))
}
