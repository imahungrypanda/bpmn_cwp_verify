//**********VARIABLE DECLARATION************//
#define paymentAmount 253
#define belowPaymentAmount 252
#define noRetryPayment 254
#define pendingPayment 255
mtype:all = {INIT other}
mtype:TermsType = {agreed failed noRetry pending}
mtype:OwnerType = {buyerName sellerName}
mtype:TermsType terms = pending
mtype:OwnerType backpackOwner = sellerName
mtype:OwnerType paymentOwner = buyerName
byte paymentOffered = pendingPayment

#define hasToken(place) (place != 0)

inline putToken(place) {
    assert (place != 1)
    place = 1
}

#define consumeToken(place) place = 0


bit StartEvent_1y8wbre = 0
bit Activity_1qm7qck_FROM_StartEvent_1y8wbre = 0
bit Gateway_12r266n_FROM_Gateway_1pm4ghz = 0
bit Gateway_12r266n_FROM_Activity_1qm7qck = 0
bit Activity_1unsjkg_FROM_Gateway_12r266n = 0
bit Gateway_0s1i42o_FROM_Activity_1unsjkg = 0
bit Gateway_0s1i42o_FROM_Activity_1t579ox = 0
bit Gateway_1pm4ghz_FROM_Gateway_0s1i42o = 0
bit Gateway_1pm4ghz_FROM_Activity_1bckz5y = 0
bit Gateway_1pm4ghz_FROM_Activity_1mktua2 = 0
bit Activity_0a5xzqf_FROM_Gateway_1pm4ghz = 0
bit Gateway_000lymc_FROM_Activity_0a5xzqf = 0
bit Activity_1qqx4aq_FROM_Gateway_000lymc = 0
bit Gateway_0cy7rs7_FROM_Activity_1qqx4aq = 0
bit Gateway_0cy7rs7_FROM_Activity_1rfm4sh = 0
bit Event_1y6wxsp_FROM_Gateway_0cy7rs7 = 0
bit Activity_1qqx4aq_END = 0
bit Activity_1rfm4sh_FROM_Gateway_000lymc = 0
bit Activity_1rfm4sh_END = 0
bit Activity_0a5xzqf_END = 0
bit Event_0wqympo_FROM_Gateway_1pm4ghz = 0
bit Activity_1bckz5y_FROM_Gateway_1pm4ghz = 0
bit Activity_1bckz5y_END = 0
bit Activity_1mktua2_FROM_Gateway_1pm4ghz = 0
bit Activity_1mktua2_END = 0
bit Activity_1unsjkg_END = 0
bit Activity_1t579ox_FROM_Gateway_12r266n = 0
bit Activity_1t579ox_END = 0
bit Activity_1qm7qck_END = 0
inline StartEvent_1y8wbre_BehaviorModel(){
    skip
}

inline Activity_1qm7qck_BehaviorModel(){
    if
        :: true -> backpackOwner = sellerName
    fi
    if
        :: true -> paymentOwner = buyerName
    fi
}

inline Activity_1unsjkg_BehaviorModel(){
    if
        :: true -> terms = agreed
        :: true -> terms = failed
    fi
}

inline Activity_0a5xzqf_BehaviorModel(){
    skip
}

inline Activity_1qqx4aq_BehaviorModel(){
    if
        :: true -> paymentOwner = sellerName
    fi
}

inline Event_1y6wxsp_BehaviorModel(){
    skip
}

inline Activity_1rfm4sh_BehaviorModel(){
    if
        :: true -> backpackOwner = buyerName
    fi
}

inline Event_0wqympo_BehaviorModel(){
    skip
}

inline Activity_1bckz5y_BehaviorModel(){
    if
        :: true -> paymentOffered = paymentAmount
        :: true -> paymentOffered = belowPaymentAmount
        :: true -> paymentOffered = noRetryPayment
    fi
}

inline Activity_1mktua2_BehaviorModel(){
    if
        :: true -> terms = agreed
        :: true -> terms = failed
        :: true -> terms = noRetry
    fi
}

inline Activity_1t579ox_BehaviorModel(){
    if
        :: true -> paymentOffered = paymentAmount
        :: true -> paymentOffered = belowPaymentAmount
    fi
}

init {
    run Process_1xbpt9j()
}

proctype Process_1xbpt9j() {
    pid me = _pid
    putToken(StartEvent_1y8wbre)
    do
    :: atomic { ((hasToken(StartEvent_1y8wbre))) ->
        StartEvent_1y8wbre_BehaviorModel()
        d_step {
            consumeToken(StartEvent_1y8wbre)
            putToken(Activity_1qm7qck_FROM_StartEvent_1y8wbre)
        }
    }
    :: atomic { ((hasToken(Activity_1qm7qck_FROM_StartEvent_1y8wbre))) ->
        Activity_1qm7qck_BehaviorModel()
        d_step {
            consumeToken(Activity_1qm7qck_FROM_StartEvent_1y8wbre)
            putToken(Gateway_12r266n_FROM_Activity_1qm7qck)
        }
    }
    :: atomic { ((hasToken(Gateway_12r266n_FROM_Gateway_1pm4ghz) || hasToken(Gateway_12r266n_FROM_Activity_1qm7qck))) ->
        d_step {
            consumeToken(Gateway_12r266n_FROM_Gateway_1pm4ghz)
            consumeToken(Gateway_12r266n_FROM_Activity_1qm7qck)
            putToken(Activity_1unsjkg_FROM_Gateway_12r266n)
            putToken(Activity_1t579ox_FROM_Gateway_12r266n)
        }
    }
    :: atomic { ((hasToken(Activity_1unsjkg_FROM_Gateway_12r266n))) ->
        Activity_1unsjkg_BehaviorModel()
        d_step {
            consumeToken(Activity_1unsjkg_FROM_Gateway_12r266n)
            putToken(Gateway_0s1i42o_FROM_Activity_1unsjkg)
        }
    }
    :: atomic { ((hasToken(Gateway_0s1i42o_FROM_Activity_1unsjkg) && hasToken(Gateway_0s1i42o_FROM_Activity_1t579ox))) ->
        d_step {
            consumeToken(Gateway_0s1i42o_FROM_Activity_1unsjkg)
            consumeToken(Gateway_0s1i42o_FROM_Activity_1t579ox)
            putToken(Gateway_1pm4ghz_FROM_Gateway_0s1i42o)
        }
    }
    :: atomic { ((hasToken(Gateway_1pm4ghz_FROM_Gateway_0s1i42o) || hasToken(Gateway_1pm4ghz_FROM_Activity_1bckz5y) || hasToken(Gateway_1pm4ghz_FROM_Activity_1mktua2))) ->
        d_step {
            consumeToken(Gateway_1pm4ghz_FROM_Gateway_0s1i42o)
            consumeToken(Gateway_1pm4ghz_FROM_Activity_1bckz5y)
            consumeToken(Gateway_1pm4ghz_FROM_Activity_1mktua2)
            if
                :: paymentOffered < paymentAmount && terms == failed -> putToken(Gateway_12r266n_FROM_Gateway_1pm4ghz)
                :: paymentOffered == paymentAmount && terms == agreed -> putToken(Activity_0a5xzqf_FROM_Gateway_1pm4ghz)
                :: paymentOffered == noRetryPayment || terms == noRetry -> putToken(Event_0wqympo_FROM_Gateway_1pm4ghz)
                :: paymentOffered < paymentAmount -> putToken(Activity_1bckz5y_FROM_Gateway_1pm4ghz)
                :: terms == failed -> putToken(Activity_1mktua2_FROM_Gateway_1pm4ghz)
                :: atomic{else -> assert false}
            fi
        }
    }
    :: atomic { ((hasToken(Activity_0a5xzqf_FROM_Gateway_1pm4ghz))) ->
        Activity_0a5xzqf_BehaviorModel()
        d_step {
            consumeToken(Activity_0a5xzqf_FROM_Gateway_1pm4ghz)
            putToken(Gateway_000lymc_FROM_Activity_0a5xzqf)
        }
    }
    :: atomic { ((hasToken(Gateway_000lymc_FROM_Activity_0a5xzqf))) ->
        d_step {
            consumeToken(Gateway_000lymc_FROM_Activity_0a5xzqf)
            putToken(Activity_1qqx4aq_FROM_Gateway_000lymc)
            putToken(Activity_1rfm4sh_FROM_Gateway_000lymc)
        }
    }
    :: atomic { ((hasToken(Activity_1qqx4aq_FROM_Gateway_000lymc))) ->
        Activity_1qqx4aq_BehaviorModel()
        d_step {
            consumeToken(Activity_1qqx4aq_FROM_Gateway_000lymc)
            putToken(Gateway_0cy7rs7_FROM_Activity_1qqx4aq)
        }
    }
    :: atomic { ((hasToken(Gateway_0cy7rs7_FROM_Activity_1qqx4aq) && hasToken(Gateway_0cy7rs7_FROM_Activity_1rfm4sh))) ->
        d_step {
            consumeToken(Gateway_0cy7rs7_FROM_Activity_1qqx4aq)
            consumeToken(Gateway_0cy7rs7_FROM_Activity_1rfm4sh)
            putToken(Event_1y6wxsp_FROM_Gateway_0cy7rs7)
        }
    }
    :: atomic { ((hasToken(Event_1y6wxsp_FROM_Gateway_0cy7rs7))) ->
        Event_1y6wxsp_BehaviorModel()
        d_step {
            consumeToken(Event_1y6wxsp_FROM_Gateway_0cy7rs7)
        }
        break
    }
    :: atomic { ((hasToken(Activity_1qqx4aq_END))) ->
        Activity_1qqx4aq_BehaviorModel()
        d_step {
            consumeToken(Activity_1qqx4aq_END)
            putToken(Activity_1qqx4aq_END)
        }
    }
    :: atomic { ((hasToken(Activity_1rfm4sh_FROM_Gateway_000lymc))) ->
        Activity_1rfm4sh_BehaviorModel()
        d_step {
            consumeToken(Activity_1rfm4sh_FROM_Gateway_000lymc)
            putToken(Gateway_0cy7rs7_FROM_Activity_1rfm4sh)
        }
    }
    :: atomic { ((hasToken(Activity_1rfm4sh_END))) ->
        Activity_1rfm4sh_BehaviorModel()
        d_step {
            consumeToken(Activity_1rfm4sh_END)
            putToken(Activity_1rfm4sh_END)
        }
    }
    :: atomic { ((hasToken(Activity_0a5xzqf_END))) ->
        Activity_0a5xzqf_BehaviorModel()
        d_step {
            consumeToken(Activity_0a5xzqf_END)
            putToken(Activity_0a5xzqf_END)
        }
    }
    :: atomic { ((hasToken(Event_0wqympo_FROM_Gateway_1pm4ghz))) ->
        Event_0wqympo_BehaviorModel()
        d_step {
            consumeToken(Event_0wqympo_FROM_Gateway_1pm4ghz)
        }
        break
    }
    :: atomic { ((hasToken(Activity_1bckz5y_FROM_Gateway_1pm4ghz))) ->
        Activity_1bckz5y_BehaviorModel()
        d_step {
            consumeToken(Activity_1bckz5y_FROM_Gateway_1pm4ghz)
            putToken(Gateway_1pm4ghz_FROM_Activity_1bckz5y)
        }
    }
    :: atomic { ((hasToken(Activity_1bckz5y_END))) ->
        Activity_1bckz5y_BehaviorModel()
        d_step {
            consumeToken(Activity_1bckz5y_END)
            putToken(Activity_1bckz5y_END)
        }
    }
    :: atomic { ((hasToken(Activity_1mktua2_FROM_Gateway_1pm4ghz))) ->
        Activity_1mktua2_BehaviorModel()
        d_step {
            consumeToken(Activity_1mktua2_FROM_Gateway_1pm4ghz)
            putToken(Gateway_1pm4ghz_FROM_Activity_1mktua2)
        }
    }
    :: atomic { ((hasToken(Activity_1mktua2_END))) ->
        Activity_1mktua2_BehaviorModel()
        d_step {
            consumeToken(Activity_1mktua2_END)
            putToken(Activity_1mktua2_END)
        }
    }
    :: atomic { ((hasToken(Activity_1unsjkg_END))) ->
        Activity_1unsjkg_BehaviorModel()
        d_step {
            consumeToken(Activity_1unsjkg_END)
            putToken(Activity_1unsjkg_END)
        }
    }
    :: atomic { ((hasToken(Activity_1t579ox_FROM_Gateway_12r266n))) ->
        Activity_1t579ox_BehaviorModel()
        d_step {
            consumeToken(Activity_1t579ox_FROM_Gateway_12r266n)
            putToken(Gateway_0s1i42o_FROM_Activity_1t579ox)
        }
    }
    :: atomic { ((hasToken(Activity_1t579ox_END))) ->
        Activity_1t579ox_BehaviorModel()
        d_step {
            consumeToken(Activity_1t579ox_END)
            putToken(Activity_1t579ox_END)
        }
    }
    :: atomic { ((hasToken(Activity_1qm7qck_END))) ->
        Activity_1qm7qck_BehaviorModel()
        d_step {
            consumeToken(Activity_1qm7qck_END)
            putToken(Activity_1qm7qck_END)
        }
    }
    od
}
