from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.contracts import RuntimeContext
from app.runtime.policy import ApprovalRequired, PolicyDenied, RuntimePolicy
from app.runtime.tokens import ShortLivedGrant, TokenInvalid


def context(mode='product_manager', expires=None):
    return RuntimeContext('t1','u1','ai-product-delivery',mode,'p1','task-1','device-1',('kb-1',),('D:/staging/project-1',),100,'low','policy-1',expires or (datetime.now(UTC)+timedelta(minutes=5)))


def test_product_manager_blocks_side_effects_and_fde_limits_files():
    policy=RuntimePolicy('policy-1')
    assert policy.check(context(), 'knowledge.search').allowed
    with pytest.raises(PolicyDenied): policy.check(context(), 'file.write', path='D:/staging/project-1/a.txt')
    with pytest.raises(PolicyDenied): policy.check(context(), 'production.workflow.update')
    with pytest.raises(PolicyDenied): policy.check(context(), 'external.publish')
    assert policy.check(context('fde'), 'file.read', path='D:/staging/project-1/a.txt').allowed
    with pytest.raises(PolicyDenied): policy.check(context('fde'), 'file.read', path='D:/other/a.txt')


def test_high_risk_action_requires_approval_and_budget_is_enforced():
    policy=RuntimePolicy('policy-1')
    with pytest.raises(ApprovalRequired) as error: policy.check(context('fde'), 'file.write', path='D:/staging/project-1/a.txt')
    assert error.value.action == 'file.write'
    with pytest.raises(PolicyDenied): policy.check(context('fde'), 'file.read', path='D:/staging/project-1/a.txt', cost_cents=101)


def test_expired_context_and_policy_version_are_rejected():
    policy=RuntimePolicy('policy-1')
    expired=datetime.now(UTC)-timedelta(seconds=1)
    with pytest.raises(PolicyDenied): policy.check(context(expires=expired), 'knowledge.search')
    bad=context(); bad=RuntimeContext(**{**bad.__dict__, 'policy_version':'old'})
    with pytest.raises(PolicyDenied): policy.check(bad, 'knowledge.search')


def test_short_lived_grant_is_bound_and_does_not_store_secrets():
    grant=ShortLivedGrant.issue('secret-key','run-1','task-1','device-1',('file.read',),datetime.now(UTC)+timedelta(minutes=1))
    assert ShortLivedGrant.verify('secret-key',grant.token,'run-1','task-1','device-1','file.read')
    assert 'secret-key' not in grant.token
    with pytest.raises(TokenInvalid): ShortLivedGrant.verify('secret-key',grant.token,'run-2','task-1','device-1','file.read')
