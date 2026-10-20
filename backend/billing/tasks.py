from celery import shared_task


@shared_task(name="billing.expire_subscriptions")
def expire_subscriptions_task() -> dict:
    from billing.services.subscription import expire_due_subscriptions

    return {"expired": expire_due_subscriptions()}
