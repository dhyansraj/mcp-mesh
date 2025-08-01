// Code generated by ent, DO NOT EDIT.

package agent

import (
	"mcp-mesh/src/core/ent/predicate"
	"time"

	"entgo.io/ent/dialect/sql"
	"entgo.io/ent/dialect/sql/sqlgraph"
)

// ID filters vertices based on their ID field.
func ID(id string) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldID, id))
}

// IDEQ applies the EQ predicate on the ID field.
func IDEQ(id string) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldID, id))
}

// IDNEQ applies the NEQ predicate on the ID field.
func IDNEQ(id string) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldID, id))
}

// IDIn applies the In predicate on the ID field.
func IDIn(ids ...string) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldID, ids...))
}

// IDNotIn applies the NotIn predicate on the ID field.
func IDNotIn(ids ...string) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldID, ids...))
}

// IDGT applies the GT predicate on the ID field.
func IDGT(id string) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldID, id))
}

// IDGTE applies the GTE predicate on the ID field.
func IDGTE(id string) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldID, id))
}

// IDLT applies the LT predicate on the ID field.
func IDLT(id string) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldID, id))
}

// IDLTE applies the LTE predicate on the ID field.
func IDLTE(id string) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldID, id))
}

// IDEqualFold applies the EqualFold predicate on the ID field.
func IDEqualFold(id string) predicate.Agent {
	return predicate.Agent(sql.FieldEqualFold(FieldID, id))
}

// IDContainsFold applies the ContainsFold predicate on the ID field.
func IDContainsFold(id string) predicate.Agent {
	return predicate.Agent(sql.FieldContainsFold(FieldID, id))
}

// Name applies equality check predicate on the "name" field. It's identical to NameEQ.
func Name(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldName, v))
}

// Version applies equality check predicate on the "version" field. It's identical to VersionEQ.
func Version(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldVersion, v))
}

// HTTPHost applies equality check predicate on the "http_host" field. It's identical to HTTPHostEQ.
func HTTPHost(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldHTTPHost, v))
}

// HTTPPort applies equality check predicate on the "http_port" field. It's identical to HTTPPortEQ.
func HTTPPort(v int) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldHTTPPort, v))
}

// Namespace applies equality check predicate on the "namespace" field. It's identical to NamespaceEQ.
func Namespace(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldNamespace, v))
}

// TotalDependencies applies equality check predicate on the "total_dependencies" field. It's identical to TotalDependenciesEQ.
func TotalDependencies(v int) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldTotalDependencies, v))
}

// DependenciesResolved applies equality check predicate on the "dependencies_resolved" field. It's identical to DependenciesResolvedEQ.
func DependenciesResolved(v int) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldDependenciesResolved, v))
}

// CreatedAt applies equality check predicate on the "created_at" field. It's identical to CreatedAtEQ.
func CreatedAt(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldCreatedAt, v))
}

// UpdatedAt applies equality check predicate on the "updated_at" field. It's identical to UpdatedAtEQ.
func UpdatedAt(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldUpdatedAt, v))
}

// LastFullRefresh applies equality check predicate on the "last_full_refresh" field. It's identical to LastFullRefreshEQ.
func LastFullRefresh(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldLastFullRefresh, v))
}

// AgentTypeEQ applies the EQ predicate on the "agent_type" field.
func AgentTypeEQ(v AgentType) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldAgentType, v))
}

// AgentTypeNEQ applies the NEQ predicate on the "agent_type" field.
func AgentTypeNEQ(v AgentType) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldAgentType, v))
}

// AgentTypeIn applies the In predicate on the "agent_type" field.
func AgentTypeIn(vs ...AgentType) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldAgentType, vs...))
}

// AgentTypeNotIn applies the NotIn predicate on the "agent_type" field.
func AgentTypeNotIn(vs ...AgentType) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldAgentType, vs...))
}

// NameEQ applies the EQ predicate on the "name" field.
func NameEQ(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldName, v))
}

// NameNEQ applies the NEQ predicate on the "name" field.
func NameNEQ(v string) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldName, v))
}

// NameIn applies the In predicate on the "name" field.
func NameIn(vs ...string) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldName, vs...))
}

// NameNotIn applies the NotIn predicate on the "name" field.
func NameNotIn(vs ...string) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldName, vs...))
}

// NameGT applies the GT predicate on the "name" field.
func NameGT(v string) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldName, v))
}

// NameGTE applies the GTE predicate on the "name" field.
func NameGTE(v string) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldName, v))
}

// NameLT applies the LT predicate on the "name" field.
func NameLT(v string) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldName, v))
}

// NameLTE applies the LTE predicate on the "name" field.
func NameLTE(v string) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldName, v))
}

// NameContains applies the Contains predicate on the "name" field.
func NameContains(v string) predicate.Agent {
	return predicate.Agent(sql.FieldContains(FieldName, v))
}

// NameHasPrefix applies the HasPrefix predicate on the "name" field.
func NameHasPrefix(v string) predicate.Agent {
	return predicate.Agent(sql.FieldHasPrefix(FieldName, v))
}

// NameHasSuffix applies the HasSuffix predicate on the "name" field.
func NameHasSuffix(v string) predicate.Agent {
	return predicate.Agent(sql.FieldHasSuffix(FieldName, v))
}

// NameEqualFold applies the EqualFold predicate on the "name" field.
func NameEqualFold(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEqualFold(FieldName, v))
}

// NameContainsFold applies the ContainsFold predicate on the "name" field.
func NameContainsFold(v string) predicate.Agent {
	return predicate.Agent(sql.FieldContainsFold(FieldName, v))
}

// VersionEQ applies the EQ predicate on the "version" field.
func VersionEQ(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldVersion, v))
}

// VersionNEQ applies the NEQ predicate on the "version" field.
func VersionNEQ(v string) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldVersion, v))
}

// VersionIn applies the In predicate on the "version" field.
func VersionIn(vs ...string) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldVersion, vs...))
}

// VersionNotIn applies the NotIn predicate on the "version" field.
func VersionNotIn(vs ...string) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldVersion, vs...))
}

// VersionGT applies the GT predicate on the "version" field.
func VersionGT(v string) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldVersion, v))
}

// VersionGTE applies the GTE predicate on the "version" field.
func VersionGTE(v string) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldVersion, v))
}

// VersionLT applies the LT predicate on the "version" field.
func VersionLT(v string) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldVersion, v))
}

// VersionLTE applies the LTE predicate on the "version" field.
func VersionLTE(v string) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldVersion, v))
}

// VersionContains applies the Contains predicate on the "version" field.
func VersionContains(v string) predicate.Agent {
	return predicate.Agent(sql.FieldContains(FieldVersion, v))
}

// VersionHasPrefix applies the HasPrefix predicate on the "version" field.
func VersionHasPrefix(v string) predicate.Agent {
	return predicate.Agent(sql.FieldHasPrefix(FieldVersion, v))
}

// VersionHasSuffix applies the HasSuffix predicate on the "version" field.
func VersionHasSuffix(v string) predicate.Agent {
	return predicate.Agent(sql.FieldHasSuffix(FieldVersion, v))
}

// VersionIsNil applies the IsNil predicate on the "version" field.
func VersionIsNil() predicate.Agent {
	return predicate.Agent(sql.FieldIsNull(FieldVersion))
}

// VersionNotNil applies the NotNil predicate on the "version" field.
func VersionNotNil() predicate.Agent {
	return predicate.Agent(sql.FieldNotNull(FieldVersion))
}

// VersionEqualFold applies the EqualFold predicate on the "version" field.
func VersionEqualFold(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEqualFold(FieldVersion, v))
}

// VersionContainsFold applies the ContainsFold predicate on the "version" field.
func VersionContainsFold(v string) predicate.Agent {
	return predicate.Agent(sql.FieldContainsFold(FieldVersion, v))
}

// HTTPHostEQ applies the EQ predicate on the "http_host" field.
func HTTPHostEQ(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldHTTPHost, v))
}

// HTTPHostNEQ applies the NEQ predicate on the "http_host" field.
func HTTPHostNEQ(v string) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldHTTPHost, v))
}

// HTTPHostIn applies the In predicate on the "http_host" field.
func HTTPHostIn(vs ...string) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldHTTPHost, vs...))
}

// HTTPHostNotIn applies the NotIn predicate on the "http_host" field.
func HTTPHostNotIn(vs ...string) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldHTTPHost, vs...))
}

// HTTPHostGT applies the GT predicate on the "http_host" field.
func HTTPHostGT(v string) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldHTTPHost, v))
}

// HTTPHostGTE applies the GTE predicate on the "http_host" field.
func HTTPHostGTE(v string) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldHTTPHost, v))
}

// HTTPHostLT applies the LT predicate on the "http_host" field.
func HTTPHostLT(v string) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldHTTPHost, v))
}

// HTTPHostLTE applies the LTE predicate on the "http_host" field.
func HTTPHostLTE(v string) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldHTTPHost, v))
}

// HTTPHostContains applies the Contains predicate on the "http_host" field.
func HTTPHostContains(v string) predicate.Agent {
	return predicate.Agent(sql.FieldContains(FieldHTTPHost, v))
}

// HTTPHostHasPrefix applies the HasPrefix predicate on the "http_host" field.
func HTTPHostHasPrefix(v string) predicate.Agent {
	return predicate.Agent(sql.FieldHasPrefix(FieldHTTPHost, v))
}

// HTTPHostHasSuffix applies the HasSuffix predicate on the "http_host" field.
func HTTPHostHasSuffix(v string) predicate.Agent {
	return predicate.Agent(sql.FieldHasSuffix(FieldHTTPHost, v))
}

// HTTPHostIsNil applies the IsNil predicate on the "http_host" field.
func HTTPHostIsNil() predicate.Agent {
	return predicate.Agent(sql.FieldIsNull(FieldHTTPHost))
}

// HTTPHostNotNil applies the NotNil predicate on the "http_host" field.
func HTTPHostNotNil() predicate.Agent {
	return predicate.Agent(sql.FieldNotNull(FieldHTTPHost))
}

// HTTPHostEqualFold applies the EqualFold predicate on the "http_host" field.
func HTTPHostEqualFold(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEqualFold(FieldHTTPHost, v))
}

// HTTPHostContainsFold applies the ContainsFold predicate on the "http_host" field.
func HTTPHostContainsFold(v string) predicate.Agent {
	return predicate.Agent(sql.FieldContainsFold(FieldHTTPHost, v))
}

// HTTPPortEQ applies the EQ predicate on the "http_port" field.
func HTTPPortEQ(v int) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldHTTPPort, v))
}

// HTTPPortNEQ applies the NEQ predicate on the "http_port" field.
func HTTPPortNEQ(v int) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldHTTPPort, v))
}

// HTTPPortIn applies the In predicate on the "http_port" field.
func HTTPPortIn(vs ...int) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldHTTPPort, vs...))
}

// HTTPPortNotIn applies the NotIn predicate on the "http_port" field.
func HTTPPortNotIn(vs ...int) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldHTTPPort, vs...))
}

// HTTPPortGT applies the GT predicate on the "http_port" field.
func HTTPPortGT(v int) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldHTTPPort, v))
}

// HTTPPortGTE applies the GTE predicate on the "http_port" field.
func HTTPPortGTE(v int) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldHTTPPort, v))
}

// HTTPPortLT applies the LT predicate on the "http_port" field.
func HTTPPortLT(v int) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldHTTPPort, v))
}

// HTTPPortLTE applies the LTE predicate on the "http_port" field.
func HTTPPortLTE(v int) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldHTTPPort, v))
}

// HTTPPortIsNil applies the IsNil predicate on the "http_port" field.
func HTTPPortIsNil() predicate.Agent {
	return predicate.Agent(sql.FieldIsNull(FieldHTTPPort))
}

// HTTPPortNotNil applies the NotNil predicate on the "http_port" field.
func HTTPPortNotNil() predicate.Agent {
	return predicate.Agent(sql.FieldNotNull(FieldHTTPPort))
}

// NamespaceEQ applies the EQ predicate on the "namespace" field.
func NamespaceEQ(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldNamespace, v))
}

// NamespaceNEQ applies the NEQ predicate on the "namespace" field.
func NamespaceNEQ(v string) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldNamespace, v))
}

// NamespaceIn applies the In predicate on the "namespace" field.
func NamespaceIn(vs ...string) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldNamespace, vs...))
}

// NamespaceNotIn applies the NotIn predicate on the "namespace" field.
func NamespaceNotIn(vs ...string) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldNamespace, vs...))
}

// NamespaceGT applies the GT predicate on the "namespace" field.
func NamespaceGT(v string) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldNamespace, v))
}

// NamespaceGTE applies the GTE predicate on the "namespace" field.
func NamespaceGTE(v string) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldNamespace, v))
}

// NamespaceLT applies the LT predicate on the "namespace" field.
func NamespaceLT(v string) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldNamespace, v))
}

// NamespaceLTE applies the LTE predicate on the "namespace" field.
func NamespaceLTE(v string) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldNamespace, v))
}

// NamespaceContains applies the Contains predicate on the "namespace" field.
func NamespaceContains(v string) predicate.Agent {
	return predicate.Agent(sql.FieldContains(FieldNamespace, v))
}

// NamespaceHasPrefix applies the HasPrefix predicate on the "namespace" field.
func NamespaceHasPrefix(v string) predicate.Agent {
	return predicate.Agent(sql.FieldHasPrefix(FieldNamespace, v))
}

// NamespaceHasSuffix applies the HasSuffix predicate on the "namespace" field.
func NamespaceHasSuffix(v string) predicate.Agent {
	return predicate.Agent(sql.FieldHasSuffix(FieldNamespace, v))
}

// NamespaceEqualFold applies the EqualFold predicate on the "namespace" field.
func NamespaceEqualFold(v string) predicate.Agent {
	return predicate.Agent(sql.FieldEqualFold(FieldNamespace, v))
}

// NamespaceContainsFold applies the ContainsFold predicate on the "namespace" field.
func NamespaceContainsFold(v string) predicate.Agent {
	return predicate.Agent(sql.FieldContainsFold(FieldNamespace, v))
}

// StatusEQ applies the EQ predicate on the "status" field.
func StatusEQ(v Status) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldStatus, v))
}

// StatusNEQ applies the NEQ predicate on the "status" field.
func StatusNEQ(v Status) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldStatus, v))
}

// StatusIn applies the In predicate on the "status" field.
func StatusIn(vs ...Status) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldStatus, vs...))
}

// StatusNotIn applies the NotIn predicate on the "status" field.
func StatusNotIn(vs ...Status) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldStatus, vs...))
}

// TotalDependenciesEQ applies the EQ predicate on the "total_dependencies" field.
func TotalDependenciesEQ(v int) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldTotalDependencies, v))
}

// TotalDependenciesNEQ applies the NEQ predicate on the "total_dependencies" field.
func TotalDependenciesNEQ(v int) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldTotalDependencies, v))
}

// TotalDependenciesIn applies the In predicate on the "total_dependencies" field.
func TotalDependenciesIn(vs ...int) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldTotalDependencies, vs...))
}

// TotalDependenciesNotIn applies the NotIn predicate on the "total_dependencies" field.
func TotalDependenciesNotIn(vs ...int) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldTotalDependencies, vs...))
}

// TotalDependenciesGT applies the GT predicate on the "total_dependencies" field.
func TotalDependenciesGT(v int) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldTotalDependencies, v))
}

// TotalDependenciesGTE applies the GTE predicate on the "total_dependencies" field.
func TotalDependenciesGTE(v int) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldTotalDependencies, v))
}

// TotalDependenciesLT applies the LT predicate on the "total_dependencies" field.
func TotalDependenciesLT(v int) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldTotalDependencies, v))
}

// TotalDependenciesLTE applies the LTE predicate on the "total_dependencies" field.
func TotalDependenciesLTE(v int) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldTotalDependencies, v))
}

// DependenciesResolvedEQ applies the EQ predicate on the "dependencies_resolved" field.
func DependenciesResolvedEQ(v int) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldDependenciesResolved, v))
}

// DependenciesResolvedNEQ applies the NEQ predicate on the "dependencies_resolved" field.
func DependenciesResolvedNEQ(v int) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldDependenciesResolved, v))
}

// DependenciesResolvedIn applies the In predicate on the "dependencies_resolved" field.
func DependenciesResolvedIn(vs ...int) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldDependenciesResolved, vs...))
}

// DependenciesResolvedNotIn applies the NotIn predicate on the "dependencies_resolved" field.
func DependenciesResolvedNotIn(vs ...int) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldDependenciesResolved, vs...))
}

// DependenciesResolvedGT applies the GT predicate on the "dependencies_resolved" field.
func DependenciesResolvedGT(v int) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldDependenciesResolved, v))
}

// DependenciesResolvedGTE applies the GTE predicate on the "dependencies_resolved" field.
func DependenciesResolvedGTE(v int) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldDependenciesResolved, v))
}

// DependenciesResolvedLT applies the LT predicate on the "dependencies_resolved" field.
func DependenciesResolvedLT(v int) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldDependenciesResolved, v))
}

// DependenciesResolvedLTE applies the LTE predicate on the "dependencies_resolved" field.
func DependenciesResolvedLTE(v int) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldDependenciesResolved, v))
}

// CreatedAtEQ applies the EQ predicate on the "created_at" field.
func CreatedAtEQ(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldCreatedAt, v))
}

// CreatedAtNEQ applies the NEQ predicate on the "created_at" field.
func CreatedAtNEQ(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldCreatedAt, v))
}

// CreatedAtIn applies the In predicate on the "created_at" field.
func CreatedAtIn(vs ...time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldCreatedAt, vs...))
}

// CreatedAtNotIn applies the NotIn predicate on the "created_at" field.
func CreatedAtNotIn(vs ...time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldCreatedAt, vs...))
}

// CreatedAtGT applies the GT predicate on the "created_at" field.
func CreatedAtGT(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldCreatedAt, v))
}

// CreatedAtGTE applies the GTE predicate on the "created_at" field.
func CreatedAtGTE(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldCreatedAt, v))
}

// CreatedAtLT applies the LT predicate on the "created_at" field.
func CreatedAtLT(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldCreatedAt, v))
}

// CreatedAtLTE applies the LTE predicate on the "created_at" field.
func CreatedAtLTE(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldCreatedAt, v))
}

// UpdatedAtEQ applies the EQ predicate on the "updated_at" field.
func UpdatedAtEQ(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldUpdatedAt, v))
}

// UpdatedAtNEQ applies the NEQ predicate on the "updated_at" field.
func UpdatedAtNEQ(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldUpdatedAt, v))
}

// UpdatedAtIn applies the In predicate on the "updated_at" field.
func UpdatedAtIn(vs ...time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldUpdatedAt, vs...))
}

// UpdatedAtNotIn applies the NotIn predicate on the "updated_at" field.
func UpdatedAtNotIn(vs ...time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldUpdatedAt, vs...))
}

// UpdatedAtGT applies the GT predicate on the "updated_at" field.
func UpdatedAtGT(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldUpdatedAt, v))
}

// UpdatedAtGTE applies the GTE predicate on the "updated_at" field.
func UpdatedAtGTE(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldUpdatedAt, v))
}

// UpdatedAtLT applies the LT predicate on the "updated_at" field.
func UpdatedAtLT(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldUpdatedAt, v))
}

// UpdatedAtLTE applies the LTE predicate on the "updated_at" field.
func UpdatedAtLTE(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldUpdatedAt, v))
}

// LastFullRefreshEQ applies the EQ predicate on the "last_full_refresh" field.
func LastFullRefreshEQ(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldEQ(FieldLastFullRefresh, v))
}

// LastFullRefreshNEQ applies the NEQ predicate on the "last_full_refresh" field.
func LastFullRefreshNEQ(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldNEQ(FieldLastFullRefresh, v))
}

// LastFullRefreshIn applies the In predicate on the "last_full_refresh" field.
func LastFullRefreshIn(vs ...time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldIn(FieldLastFullRefresh, vs...))
}

// LastFullRefreshNotIn applies the NotIn predicate on the "last_full_refresh" field.
func LastFullRefreshNotIn(vs ...time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldNotIn(FieldLastFullRefresh, vs...))
}

// LastFullRefreshGT applies the GT predicate on the "last_full_refresh" field.
func LastFullRefreshGT(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldGT(FieldLastFullRefresh, v))
}

// LastFullRefreshGTE applies the GTE predicate on the "last_full_refresh" field.
func LastFullRefreshGTE(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldGTE(FieldLastFullRefresh, v))
}

// LastFullRefreshLT applies the LT predicate on the "last_full_refresh" field.
func LastFullRefreshLT(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldLT(FieldLastFullRefresh, v))
}

// LastFullRefreshLTE applies the LTE predicate on the "last_full_refresh" field.
func LastFullRefreshLTE(v time.Time) predicate.Agent {
	return predicate.Agent(sql.FieldLTE(FieldLastFullRefresh, v))
}

// HasCapabilities applies the HasEdge predicate on the "capabilities" edge.
func HasCapabilities() predicate.Agent {
	return predicate.Agent(func(s *sql.Selector) {
		step := sqlgraph.NewStep(
			sqlgraph.From(Table, FieldID),
			sqlgraph.Edge(sqlgraph.O2M, false, CapabilitiesTable, CapabilitiesColumn),
		)
		sqlgraph.HasNeighbors(s, step)
	})
}

// HasCapabilitiesWith applies the HasEdge predicate on the "capabilities" edge with a given conditions (other predicates).
func HasCapabilitiesWith(preds ...predicate.Capability) predicate.Agent {
	return predicate.Agent(func(s *sql.Selector) {
		step := newCapabilitiesStep()
		sqlgraph.HasNeighborsWith(s, step, func(s *sql.Selector) {
			for _, p := range preds {
				p(s)
			}
		})
	})
}

// HasEvents applies the HasEdge predicate on the "events" edge.
func HasEvents() predicate.Agent {
	return predicate.Agent(func(s *sql.Selector) {
		step := sqlgraph.NewStep(
			sqlgraph.From(Table, FieldID),
			sqlgraph.Edge(sqlgraph.O2M, false, EventsTable, EventsColumn),
		)
		sqlgraph.HasNeighbors(s, step)
	})
}

// HasEventsWith applies the HasEdge predicate on the "events" edge with a given conditions (other predicates).
func HasEventsWith(preds ...predicate.RegistryEvent) predicate.Agent {
	return predicate.Agent(func(s *sql.Selector) {
		step := newEventsStep()
		sqlgraph.HasNeighborsWith(s, step, func(s *sql.Selector) {
			for _, p := range preds {
				p(s)
			}
		})
	})
}

// And groups predicates with the AND operator between them.
func And(predicates ...predicate.Agent) predicate.Agent {
	return predicate.Agent(sql.AndPredicates(predicates...))
}

// Or groups predicates with the OR operator between them.
func Or(predicates ...predicate.Agent) predicate.Agent {
	return predicate.Agent(sql.OrPredicates(predicates...))
}

// Not applies the not operator on the given predicate.
func Not(p predicate.Agent) predicate.Agent {
	return predicate.Agent(sql.NotPredicates(p))
}
