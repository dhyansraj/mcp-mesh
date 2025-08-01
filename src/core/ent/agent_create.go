// Code generated by ent, DO NOT EDIT.

package ent

import (
	"context"
	"errors"
	"fmt"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
	"mcp-mesh/src/core/ent/registryevent"
	"time"

	"entgo.io/ent/dialect/sql/sqlgraph"
	"entgo.io/ent/schema/field"
)

// AgentCreate is the builder for creating a Agent entity.
type AgentCreate struct {
	config
	mutation *AgentMutation
	hooks    []Hook
}

// SetAgentType sets the "agent_type" field.
func (ac *AgentCreate) SetAgentType(at agent.AgentType) *AgentCreate {
	ac.mutation.SetAgentType(at)
	return ac
}

// SetNillableAgentType sets the "agent_type" field if the given value is not nil.
func (ac *AgentCreate) SetNillableAgentType(at *agent.AgentType) *AgentCreate {
	if at != nil {
		ac.SetAgentType(*at)
	}
	return ac
}

// SetName sets the "name" field.
func (ac *AgentCreate) SetName(s string) *AgentCreate {
	ac.mutation.SetName(s)
	return ac
}

// SetVersion sets the "version" field.
func (ac *AgentCreate) SetVersion(s string) *AgentCreate {
	ac.mutation.SetVersion(s)
	return ac
}

// SetNillableVersion sets the "version" field if the given value is not nil.
func (ac *AgentCreate) SetNillableVersion(s *string) *AgentCreate {
	if s != nil {
		ac.SetVersion(*s)
	}
	return ac
}

// SetHTTPHost sets the "http_host" field.
func (ac *AgentCreate) SetHTTPHost(s string) *AgentCreate {
	ac.mutation.SetHTTPHost(s)
	return ac
}

// SetNillableHTTPHost sets the "http_host" field if the given value is not nil.
func (ac *AgentCreate) SetNillableHTTPHost(s *string) *AgentCreate {
	if s != nil {
		ac.SetHTTPHost(*s)
	}
	return ac
}

// SetHTTPPort sets the "http_port" field.
func (ac *AgentCreate) SetHTTPPort(i int) *AgentCreate {
	ac.mutation.SetHTTPPort(i)
	return ac
}

// SetNillableHTTPPort sets the "http_port" field if the given value is not nil.
func (ac *AgentCreate) SetNillableHTTPPort(i *int) *AgentCreate {
	if i != nil {
		ac.SetHTTPPort(*i)
	}
	return ac
}

// SetNamespace sets the "namespace" field.
func (ac *AgentCreate) SetNamespace(s string) *AgentCreate {
	ac.mutation.SetNamespace(s)
	return ac
}

// SetNillableNamespace sets the "namespace" field if the given value is not nil.
func (ac *AgentCreate) SetNillableNamespace(s *string) *AgentCreate {
	if s != nil {
		ac.SetNamespace(*s)
	}
	return ac
}

// SetStatus sets the "status" field.
func (ac *AgentCreate) SetStatus(a agent.Status) *AgentCreate {
	ac.mutation.SetStatus(a)
	return ac
}

// SetNillableStatus sets the "status" field if the given value is not nil.
func (ac *AgentCreate) SetNillableStatus(a *agent.Status) *AgentCreate {
	if a != nil {
		ac.SetStatus(*a)
	}
	return ac
}

// SetTotalDependencies sets the "total_dependencies" field.
func (ac *AgentCreate) SetTotalDependencies(i int) *AgentCreate {
	ac.mutation.SetTotalDependencies(i)
	return ac
}

// SetNillableTotalDependencies sets the "total_dependencies" field if the given value is not nil.
func (ac *AgentCreate) SetNillableTotalDependencies(i *int) *AgentCreate {
	if i != nil {
		ac.SetTotalDependencies(*i)
	}
	return ac
}

// SetDependenciesResolved sets the "dependencies_resolved" field.
func (ac *AgentCreate) SetDependenciesResolved(i int) *AgentCreate {
	ac.mutation.SetDependenciesResolved(i)
	return ac
}

// SetNillableDependenciesResolved sets the "dependencies_resolved" field if the given value is not nil.
func (ac *AgentCreate) SetNillableDependenciesResolved(i *int) *AgentCreate {
	if i != nil {
		ac.SetDependenciesResolved(*i)
	}
	return ac
}

// SetCreatedAt sets the "created_at" field.
func (ac *AgentCreate) SetCreatedAt(t time.Time) *AgentCreate {
	ac.mutation.SetCreatedAt(t)
	return ac
}

// SetNillableCreatedAt sets the "created_at" field if the given value is not nil.
func (ac *AgentCreate) SetNillableCreatedAt(t *time.Time) *AgentCreate {
	if t != nil {
		ac.SetCreatedAt(*t)
	}
	return ac
}

// SetUpdatedAt sets the "updated_at" field.
func (ac *AgentCreate) SetUpdatedAt(t time.Time) *AgentCreate {
	ac.mutation.SetUpdatedAt(t)
	return ac
}

// SetNillableUpdatedAt sets the "updated_at" field if the given value is not nil.
func (ac *AgentCreate) SetNillableUpdatedAt(t *time.Time) *AgentCreate {
	if t != nil {
		ac.SetUpdatedAt(*t)
	}
	return ac
}

// SetLastFullRefresh sets the "last_full_refresh" field.
func (ac *AgentCreate) SetLastFullRefresh(t time.Time) *AgentCreate {
	ac.mutation.SetLastFullRefresh(t)
	return ac
}

// SetNillableLastFullRefresh sets the "last_full_refresh" field if the given value is not nil.
func (ac *AgentCreate) SetNillableLastFullRefresh(t *time.Time) *AgentCreate {
	if t != nil {
		ac.SetLastFullRefresh(*t)
	}
	return ac
}

// SetID sets the "id" field.
func (ac *AgentCreate) SetID(s string) *AgentCreate {
	ac.mutation.SetID(s)
	return ac
}

// AddCapabilityIDs adds the "capabilities" edge to the Capability entity by IDs.
func (ac *AgentCreate) AddCapabilityIDs(ids ...int) *AgentCreate {
	ac.mutation.AddCapabilityIDs(ids...)
	return ac
}

// AddCapabilities adds the "capabilities" edges to the Capability entity.
func (ac *AgentCreate) AddCapabilities(c ...*Capability) *AgentCreate {
	ids := make([]int, len(c))
	for i := range c {
		ids[i] = c[i].ID
	}
	return ac.AddCapabilityIDs(ids...)
}

// AddEventIDs adds the "events" edge to the RegistryEvent entity by IDs.
func (ac *AgentCreate) AddEventIDs(ids ...int) *AgentCreate {
	ac.mutation.AddEventIDs(ids...)
	return ac
}

// AddEvents adds the "events" edges to the RegistryEvent entity.
func (ac *AgentCreate) AddEvents(r ...*RegistryEvent) *AgentCreate {
	ids := make([]int, len(r))
	for i := range r {
		ids[i] = r[i].ID
	}
	return ac.AddEventIDs(ids...)
}

// Mutation returns the AgentMutation object of the builder.
func (ac *AgentCreate) Mutation() *AgentMutation {
	return ac.mutation
}

// Save creates the Agent in the database.
func (ac *AgentCreate) Save(ctx context.Context) (*Agent, error) {
	ac.defaults()
	return withHooks(ctx, ac.sqlSave, ac.mutation, ac.hooks)
}

// SaveX calls Save and panics if Save returns an error.
func (ac *AgentCreate) SaveX(ctx context.Context) *Agent {
	v, err := ac.Save(ctx)
	if err != nil {
		panic(err)
	}
	return v
}

// Exec executes the query.
func (ac *AgentCreate) Exec(ctx context.Context) error {
	_, err := ac.Save(ctx)
	return err
}

// ExecX is like Exec, but panics if an error occurs.
func (ac *AgentCreate) ExecX(ctx context.Context) {
	if err := ac.Exec(ctx); err != nil {
		panic(err)
	}
}

// defaults sets the default values of the builder before save.
func (ac *AgentCreate) defaults() {
	if _, ok := ac.mutation.AgentType(); !ok {
		v := agent.DefaultAgentType
		ac.mutation.SetAgentType(v)
	}
	if _, ok := ac.mutation.Namespace(); !ok {
		v := agent.DefaultNamespace
		ac.mutation.SetNamespace(v)
	}
	if _, ok := ac.mutation.Status(); !ok {
		v := agent.DefaultStatus
		ac.mutation.SetStatus(v)
	}
	if _, ok := ac.mutation.TotalDependencies(); !ok {
		v := agent.DefaultTotalDependencies
		ac.mutation.SetTotalDependencies(v)
	}
	if _, ok := ac.mutation.DependenciesResolved(); !ok {
		v := agent.DefaultDependenciesResolved
		ac.mutation.SetDependenciesResolved(v)
	}
	if _, ok := ac.mutation.CreatedAt(); !ok {
		v := agent.DefaultCreatedAt()
		ac.mutation.SetCreatedAt(v)
	}
	if _, ok := ac.mutation.UpdatedAt(); !ok {
		v := agent.DefaultUpdatedAt()
		ac.mutation.SetUpdatedAt(v)
	}
	if _, ok := ac.mutation.LastFullRefresh(); !ok {
		v := agent.DefaultLastFullRefresh()
		ac.mutation.SetLastFullRefresh(v)
	}
}

// check runs all checks and user-defined validators on the builder.
func (ac *AgentCreate) check() error {
	if _, ok := ac.mutation.AgentType(); !ok {
		return &ValidationError{Name: "agent_type", err: errors.New(`ent: missing required field "Agent.agent_type"`)}
	}
	if v, ok := ac.mutation.AgentType(); ok {
		if err := agent.AgentTypeValidator(v); err != nil {
			return &ValidationError{Name: "agent_type", err: fmt.Errorf(`ent: validator failed for field "Agent.agent_type": %w`, err)}
		}
	}
	if _, ok := ac.mutation.Name(); !ok {
		return &ValidationError{Name: "name", err: errors.New(`ent: missing required field "Agent.name"`)}
	}
	if _, ok := ac.mutation.Namespace(); !ok {
		return &ValidationError{Name: "namespace", err: errors.New(`ent: missing required field "Agent.namespace"`)}
	}
	if _, ok := ac.mutation.Status(); !ok {
		return &ValidationError{Name: "status", err: errors.New(`ent: missing required field "Agent.status"`)}
	}
	if v, ok := ac.mutation.Status(); ok {
		if err := agent.StatusValidator(v); err != nil {
			return &ValidationError{Name: "status", err: fmt.Errorf(`ent: validator failed for field "Agent.status": %w`, err)}
		}
	}
	if _, ok := ac.mutation.TotalDependencies(); !ok {
		return &ValidationError{Name: "total_dependencies", err: errors.New(`ent: missing required field "Agent.total_dependencies"`)}
	}
	if _, ok := ac.mutation.DependenciesResolved(); !ok {
		return &ValidationError{Name: "dependencies_resolved", err: errors.New(`ent: missing required field "Agent.dependencies_resolved"`)}
	}
	if _, ok := ac.mutation.CreatedAt(); !ok {
		return &ValidationError{Name: "created_at", err: errors.New(`ent: missing required field "Agent.created_at"`)}
	}
	if _, ok := ac.mutation.UpdatedAt(); !ok {
		return &ValidationError{Name: "updated_at", err: errors.New(`ent: missing required field "Agent.updated_at"`)}
	}
	if _, ok := ac.mutation.LastFullRefresh(); !ok {
		return &ValidationError{Name: "last_full_refresh", err: errors.New(`ent: missing required field "Agent.last_full_refresh"`)}
	}
	return nil
}

func (ac *AgentCreate) sqlSave(ctx context.Context) (*Agent, error) {
	if err := ac.check(); err != nil {
		return nil, err
	}
	_node, _spec := ac.createSpec()
	if err := sqlgraph.CreateNode(ctx, ac.driver, _spec); err != nil {
		if sqlgraph.IsConstraintError(err) {
			err = &ConstraintError{msg: err.Error(), wrap: err}
		}
		return nil, err
	}
	if _spec.ID.Value != nil {
		if id, ok := _spec.ID.Value.(string); ok {
			_node.ID = id
		} else {
			return nil, fmt.Errorf("unexpected Agent.ID type: %T", _spec.ID.Value)
		}
	}
	ac.mutation.id = &_node.ID
	ac.mutation.done = true
	return _node, nil
}

func (ac *AgentCreate) createSpec() (*Agent, *sqlgraph.CreateSpec) {
	var (
		_node = &Agent{config: ac.config}
		_spec = sqlgraph.NewCreateSpec(agent.Table, sqlgraph.NewFieldSpec(agent.FieldID, field.TypeString))
	)
	if id, ok := ac.mutation.ID(); ok {
		_node.ID = id
		_spec.ID.Value = id
	}
	if value, ok := ac.mutation.AgentType(); ok {
		_spec.SetField(agent.FieldAgentType, field.TypeEnum, value)
		_node.AgentType = value
	}
	if value, ok := ac.mutation.Name(); ok {
		_spec.SetField(agent.FieldName, field.TypeString, value)
		_node.Name = value
	}
	if value, ok := ac.mutation.Version(); ok {
		_spec.SetField(agent.FieldVersion, field.TypeString, value)
		_node.Version = value
	}
	if value, ok := ac.mutation.HTTPHost(); ok {
		_spec.SetField(agent.FieldHTTPHost, field.TypeString, value)
		_node.HTTPHost = value
	}
	if value, ok := ac.mutation.HTTPPort(); ok {
		_spec.SetField(agent.FieldHTTPPort, field.TypeInt, value)
		_node.HTTPPort = value
	}
	if value, ok := ac.mutation.Namespace(); ok {
		_spec.SetField(agent.FieldNamespace, field.TypeString, value)
		_node.Namespace = value
	}
	if value, ok := ac.mutation.Status(); ok {
		_spec.SetField(agent.FieldStatus, field.TypeEnum, value)
		_node.Status = value
	}
	if value, ok := ac.mutation.TotalDependencies(); ok {
		_spec.SetField(agent.FieldTotalDependencies, field.TypeInt, value)
		_node.TotalDependencies = value
	}
	if value, ok := ac.mutation.DependenciesResolved(); ok {
		_spec.SetField(agent.FieldDependenciesResolved, field.TypeInt, value)
		_node.DependenciesResolved = value
	}
	if value, ok := ac.mutation.CreatedAt(); ok {
		_spec.SetField(agent.FieldCreatedAt, field.TypeTime, value)
		_node.CreatedAt = value
	}
	if value, ok := ac.mutation.UpdatedAt(); ok {
		_spec.SetField(agent.FieldUpdatedAt, field.TypeTime, value)
		_node.UpdatedAt = value
	}
	if value, ok := ac.mutation.LastFullRefresh(); ok {
		_spec.SetField(agent.FieldLastFullRefresh, field.TypeTime, value)
		_node.LastFullRefresh = value
	}
	if nodes := ac.mutation.CapabilitiesIDs(); len(nodes) > 0 {
		edge := &sqlgraph.EdgeSpec{
			Rel:     sqlgraph.O2M,
			Inverse: false,
			Table:   agent.CapabilitiesTable,
			Columns: []string{agent.CapabilitiesColumn},
			Bidi:    false,
			Target: &sqlgraph.EdgeTarget{
				IDSpec: sqlgraph.NewFieldSpec(capability.FieldID, field.TypeInt),
			},
		}
		for _, k := range nodes {
			edge.Target.Nodes = append(edge.Target.Nodes, k)
		}
		_spec.Edges = append(_spec.Edges, edge)
	}
	if nodes := ac.mutation.EventsIDs(); len(nodes) > 0 {
		edge := &sqlgraph.EdgeSpec{
			Rel:     sqlgraph.O2M,
			Inverse: false,
			Table:   agent.EventsTable,
			Columns: []string{agent.EventsColumn},
			Bidi:    false,
			Target: &sqlgraph.EdgeTarget{
				IDSpec: sqlgraph.NewFieldSpec(registryevent.FieldID, field.TypeInt),
			},
		}
		for _, k := range nodes {
			edge.Target.Nodes = append(edge.Target.Nodes, k)
		}
		_spec.Edges = append(_spec.Edges, edge)
	}
	return _node, _spec
}

// AgentCreateBulk is the builder for creating many Agent entities in bulk.
type AgentCreateBulk struct {
	config
	err      error
	builders []*AgentCreate
}

// Save creates the Agent entities in the database.
func (acb *AgentCreateBulk) Save(ctx context.Context) ([]*Agent, error) {
	if acb.err != nil {
		return nil, acb.err
	}
	specs := make([]*sqlgraph.CreateSpec, len(acb.builders))
	nodes := make([]*Agent, len(acb.builders))
	mutators := make([]Mutator, len(acb.builders))
	for i := range acb.builders {
		func(i int, root context.Context) {
			builder := acb.builders[i]
			builder.defaults()
			var mut Mutator = MutateFunc(func(ctx context.Context, m Mutation) (Value, error) {
				mutation, ok := m.(*AgentMutation)
				if !ok {
					return nil, fmt.Errorf("unexpected mutation type %T", m)
				}
				if err := builder.check(); err != nil {
					return nil, err
				}
				builder.mutation = mutation
				var err error
				nodes[i], specs[i] = builder.createSpec()
				if i < len(mutators)-1 {
					_, err = mutators[i+1].Mutate(root, acb.builders[i+1].mutation)
				} else {
					spec := &sqlgraph.BatchCreateSpec{Nodes: specs}
					// Invoke the actual operation on the latest mutation in the chain.
					if err = sqlgraph.BatchCreate(ctx, acb.driver, spec); err != nil {
						if sqlgraph.IsConstraintError(err) {
							err = &ConstraintError{msg: err.Error(), wrap: err}
						}
					}
				}
				if err != nil {
					return nil, err
				}
				mutation.id = &nodes[i].ID
				mutation.done = true
				return nodes[i], nil
			})
			for i := len(builder.hooks) - 1; i >= 0; i-- {
				mut = builder.hooks[i](mut)
			}
			mutators[i] = mut
		}(i, ctx)
	}
	if len(mutators) > 0 {
		if _, err := mutators[0].Mutate(ctx, acb.builders[0].mutation); err != nil {
			return nil, err
		}
	}
	return nodes, nil
}

// SaveX is like Save, but panics if an error occurs.
func (acb *AgentCreateBulk) SaveX(ctx context.Context) []*Agent {
	v, err := acb.Save(ctx)
	if err != nil {
		panic(err)
	}
	return v
}

// Exec executes the query.
func (acb *AgentCreateBulk) Exec(ctx context.Context) error {
	_, err := acb.Save(ctx)
	return err
}

// ExecX is like Exec, but panics if an error occurs.
func (acb *AgentCreateBulk) ExecX(ctx context.Context) {
	if err := acb.Exec(ctx); err != nil {
		panic(err)
	}
}
