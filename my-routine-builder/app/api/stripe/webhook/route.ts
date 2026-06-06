import { NextResponse } from 'next/server';
import { stripe } from '@/lib/stripe';
import { createServiceClient } from '@/lib/supabase-server';
import type Stripe from 'stripe';

export const runtime = 'nodejs';

export async function POST(request: Request) {
  const body = await request.text();
  const sig = request.headers.get('stripe-signature');
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET!;

  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(body, sig!, webhookSecret);
  } catch (err) {
    console.error('Webhook signature verification failed:', err);
    return NextResponse.json({ error: 'Invalid signature' }, { status: 400 });
  }

  const supabase = createServiceClient();

  try {
    switch (event.type) {
      case 'checkout.session.completed': {
        const session = event.data.object as Stripe.Checkout.Session;
        const userId = session.metadata?.user_id;
        if (!userId) break;

        const subscriptionId = session.subscription as string;
        const subscription = await stripe.subscriptions.retrieve(subscriptionId);
        // current_period_end is available on the subscription object
        const periodEnd = (subscription as unknown as { current_period_end: number }).current_period_end;
        const currentPeriodEnd = periodEnd ? new Date(periodEnd * 1000).toISOString() : null;

        await supabase
          .from('subscriptions')
          .upsert(
            {
              user_id: userId,
              stripe_customer_id: session.customer as string,
              stripe_subscription_id: subscriptionId,
              plan: 'pro',
              current_period_end: currentPeriodEnd,
            },
            { onConflict: 'user_id' }
          );
        break;
      }

      case 'customer.subscription.updated': {
        const subscription = event.data.object as Stripe.Subscription;
        const customerId = subscription.customer as string;
        const periodEnd = (subscription as unknown as { current_period_end?: number }).current_period_end;
        const currentPeriodEnd = periodEnd ? new Date(periodEnd * 1000).toISOString() : null;

        const status = subscription.status;
        const plan = status === 'active' || status === 'trialing' ? 'pro' : 'free';

        await supabase
          .from('subscriptions')
          .update({
            stripe_subscription_id: subscription.id,
            plan,
            current_period_end: currentPeriodEnd,
          })
          .eq('stripe_customer_id', customerId);
        break;
      }

      case 'customer.subscription.deleted': {
        const subscription = event.data.object as Stripe.Subscription;
        const customerId = subscription.customer as string;

        await supabase
          .from('subscriptions')
          .update({
            plan: 'free',
            stripe_subscription_id: null,
            current_period_end: null,
          })
          .eq('stripe_customer_id', customerId);
        break;
      }

      case 'invoice.payment_failed': {
        const invoice = event.data.object as Stripe.Invoice;
        const customerId = invoice.customer as string;

        await supabase
          .from('subscriptions')
          .update({ plan: 'free' })
          .eq('stripe_customer_id', customerId);
        break;
      }

      default:
        // Unhandled event type
        break;
    }

    return NextResponse.json({ received: true });
  } catch (e) {
    console.error('Webhook handler error:', e);
    return NextResponse.json({ error: 'Webhook handler failed' }, { status: 500 });
  }
}
