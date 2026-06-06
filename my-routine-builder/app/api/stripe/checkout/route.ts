import { NextResponse } from 'next/server';
import { createClient } from '@/lib/supabase-server';
import { stripe } from '@/lib/stripe';

export async function POST() {
  try {
    const supabase = await createClient();
    const { data: { user } } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const email = user.email;
    const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000';

    // Check if user already has a Stripe customer
    const { data: subscription } = await supabase
      .from('subscriptions')
      .select('stripe_customer_id, plan')
      .eq('user_id', user.id)
      .single();

    if (subscription?.plan === 'pro') {
      return NextResponse.json({ error: 'Already on Pro plan' }, { status: 400 });
    }

    let customerId = subscription?.stripe_customer_id;

    if (!customerId) {
      const customer = await stripe.customers.create({
        email: email ?? undefined,
        metadata: { supabase_user_id: user.id },
      });
      customerId = customer.id;

      // Upsert subscription row with customer ID
      await supabase
        .from('subscriptions')
        .upsert(
          { user_id: user.id, stripe_customer_id: customerId, plan: 'free' },
          { onConflict: 'user_id' }
        );
    }

    const session = await stripe.checkout.sessions.create({
      customer: customerId,
      mode: 'subscription',
      payment_method_types: ['card'],
      line_items: [
        {
          price: process.env.STRIPE_PRO_PRICE_ID!,
          quantity: 1,
        },
      ],
      success_url: `${appUrl}/dashboard?upgraded=1`,
      cancel_url: `${appUrl}/upgrade?canceled=1`,
      metadata: {
        user_id: user.id,
      },
    });

    return NextResponse.json({ url: session.url });
  } catch (e) {
    console.error('Checkout error:', e);
    return NextResponse.json({ error: 'Failed to create checkout session' }, { status: 500 });
  }
}
