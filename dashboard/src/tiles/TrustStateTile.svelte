<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // B2.9: active trust grants from trust_granted/renewed minus revoked.
  let grants = $state({}); // key role/class -> {role, class, expires, revoked}
  let connected = $state(false);
  let unsubscribe;

  function key(p) {
    return `${p.role_name}/${p.task_class}`;
  }

  function apply(msg) {
    const p = msg.payload;
    const k = key(p);
    const next = { ...grants };
    if (msg.event_type === 'trust_granted') {
      next[k] = { role: p.role_name, klass: p.task_class, expires: p.expires_at_millis, revoked: false };
    } else if (msg.event_type === 'trust_renewed' && next[k]) {
      next[k] = { ...next[k], expires: p.new_expires_at_millis, revoked: false };
    } else if (msg.event_type === 'trust_revoked' && next[k]) {
      next[k] = { ...next[k], revoked: true };
    }
    grants = next;
  }

  onMount(() => {
    unsubscribe = subscribe(['trust_granted', 'trust_renewed', 'trust_revoked'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Trust state</h2>
  <small>proj_trust_grants</small>
  {#if Object.keys(grants).length === 0}
    <p>no trust state yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each Object.entries(grants) as [k, g] (k)}
        <li>
          {g.role} / {g.klass} — {g.revoked ? '[revoked]' : `expires ${g.expires}`}
        </li>
      {/each}
    </ul>
  {/if}
</section>
