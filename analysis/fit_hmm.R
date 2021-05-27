library(tidyverse)
library(cmdstanr)
library(rstan)

init_prob <- c(.5, .5)
trans_prob <- array(c(0.8, 0.2, 0.95, 0.05), c(2, 2))
lambda <- c(5, .125)

generate_bouts <- function(N, init_prob, trans_prob, lambda){
  #initialization
  IRTs <- c()
  states <- c()
  state_num <- length(trans_prob[1,])
  cum_trans_prob <- rbind(rep(0, state_num), apply(trans_prob, 2, cumsum))
  cum_init_prob <- c(0, cumsum(init_prob))
  
  #initial state
  temp_runif <- runif(1)
  for(i in 1:state_num){
    if(cum_init_prob[i] <= temp_runif && temp_runif < cum_init_prob[i+1]){
      cur_state = i
      break
    }
  }
  
  #generate bouts
  for(i in 1:N){
    #gennerate an IRT
    IRTs <- c(IRTs, rexp(1, lambda[cur_state]))
    states <- c(states, cur_state)
    #next state
    temp_runif <- runif(1)
    for(j in 1:state_num){
      if(cum_trans_prob[j] <= temp_runif && temp_runif < cum_trans_prob[j+1]){
        cur_state = j
        break
      }
    }
  }
  return(data.frame(IRT = IRTs, label = states))
}

sim_bout_data <- generate_bouts(2000, init_prob, trans_prob, lambda)

hmm <- cmdstan_model("./analysis/hmm.stan")
sample_data <- list(T = nrow(sim_bout_data), K = 2, y = sim_bout_data$IRT)

fit <- hmm$sample(data = sample_data,
                  parallel_chains = 4,
                  chains = 4,
                  iter_warmup = 1000,
                  iter_sampling = 1000)

fit_result <- rstan::read_stan_csv(fit$output_files())
extracts <- rstan::extract(fit_result)

opt_state_seq <- extracts$zstar[1,]

res_classify <- data.frame(ser_num = seq(1, 2000, 1),
                           IRT = sim_bout_data$IRT,
                           cor_label = sim_bout_data$label,
                           est_label = abs(opt_state_seq - 3))

ggplot(data = res_classify, aes(x = ser_num)) +
  geom_line(aes(y = est_label, color = "red"), size = 1) +
  geom_point(aes(y = cor_label, color = "blue"), size = 2) +
  xlim(1, 50) +
  scale_color_hue(name = "type of labels", labels= c("estimated",  "correct")) +
  labs(x = "serial number of labels (states)", y = "labels (states)") + 
  theme(axis.title.x = element_text(size = 15),
        axis.title.y = element_text(size = 15),
        axis.text.x = element_text(size = 10),
        axis.text.y = element_text(size = 10),
        aspect.ratio = .75)
