#! python3
import logging
import requests
import json
import math
from datetime import datetime, date, time
import time

baseVol = 3 #base long run daily volatility percent
customShortVol = 1 #custom volatility factor to be applied to rolling 30 day volatility
daysAdded = 0.5 #days added to volatility calculation to adjust for sharp spikes in price
dailyPercentReturn = 0.05 #expected daily return of bitcoin against usd

#bullishness, values over 1 mean i think bitcoin price is going up
#2=no spread on buys, 0=double spread on buys, backwards for sells
bullishness = 1

#custom uncertainty to adjust uncertainty manually
customUncertainty = 1.2 #1.05 post fix for asset same price

#size of orders
bestShares = 4
goodShares = 3
okShares = 2

gmtOffset = 0 #time zone offset

predictiousUrl = 'https://api.predictious.com/v1/'
predictiousKey = '' #ENTER API KEY HERE

class PriceContract:
	def __init__(self, id=None, endDate=None, price=0.0, name=None):
		self.id = id
		self.endDate = endDate
		self.price = price
		self.name = name

def normdist(contractPrice, currentPrice, sd):
	return 0.500 * (1 + math.erf((contractPrice - currentPrice)/math.sqrt(2 * sd**2)))
	
def calcodds(price, strike, days, vol):
	p=price
	q=strike
	t=days/365
	v=vol/100 * math.sqrt(365)
	
	vt=v*math.sqrt(t)
	lnpq=math.log(q/p)
	d1=lnpq / vt
  
	y=1/(1+.2316419*abs(d1))
	z=0.3989423*math.exp(-((d1*d1)/2))
	y5=1.330274*y**5
	y4=1.821256*y**4
	y3=1.781478*y**3
	y2=.356538*y**2
	y1=.3193815*y
	x=1-z*(y5-y4+y3-y2+y1)
  
	if d1>0:
		x = 1-x
	
	return x

def do_call(callName, payload):
	headers = {
		'X-Predictious-Key' : predictiousKey,
		'Content-Type' : 'application/json'
	}
	payloadJson = json.dumps(payload)
	r = requests.post(predictiousUrl + callName, data=payloadJson, headers=headers)
	return r.json()

def optimizeOrderPrice(orderPrice, isAsk, bothWays):
	newPrice = orderPrice
	if isAsk or bothWays:
		if(orderPrice >=25000 and orderPrice < 29000):
			newPrice = 24000
		elif orderPrice >= 100000 and orderPrice < 105000:
			newPrice = 99000
	if not isAsk or bothWays:
		if orderPrice > 895000 and orderPrice <= 900000:
			newPrice = 901000
		elif orderPrice > 971000 and orderPrice <= 975000:
			newPrice = 976000
	return newPrice
	
def optimizeQuantity(quantity, orderPrice, isAsk):
	if isAsk:
		if(orderPrice >=30000 and orderPrice < 80000):
			quantity *= 0.75
		elif orderPrice <= 30000:
			quantity *= 0.5
		elif orderPrice > 975000:
			quantity *= 2.5
		elif orderPrice <= 975000 and orderPrice > 920000:
			quantity *= 1.5
	else:
		if(orderPrice >=25000 and orderPrice < 80000):
			quantity *= 1.5
		elif orderPrice < 25000:
			quantity *= 2.5
		elif orderPrice >= 970000:
			quantity *= 0.5
		elif orderPrice < 970000 and orderPrice > 920000:
			quantity *= 0.75
	return int(quantity)

while 1: 
	try:
		headers = {'X-Predictious-Key' : predictiousKey}
		priceContracts = []
		contractIds = []

		#get all bitcoin price contracts
		contracts = requests.get(predictiousUrl + 'contracts', data={}, headers=headers).json()
		for contract in contracts:
			if contract['Name'].startswith('Price of Bitcoin'):
				id = contract['Id']
				endDate = datetime.strptime(contract['EventDate'], '%Y-%m-%dT%H:%M:%S')
				name = contract['Name']
				price = name[name.find('$')+1:]
				#print('Found contract ' + name +  ' with price ' + price)
				priceContracts.append(PriceContract(id, endDate, float(price), name))
				contractIds.append(id)
					
		#cancel orders on those contracts
		ordersToCancel = []
		orders = requests.get(predictiousUrl + 'orders', data={}, headers=headers).json()
		for order in orders:
			if order['ContractId'] in contractIds:
				ordersToCancel.append({'Id' : order['OrderId']})

		do_call('cancelorders', ordersToCancel)
		print('Orders cancelled')
		
		#get current positions
		wallet = requests.get(predictiousUrl + 'wallet', data={}, headers=headers).json()
		shares = {}
		for share in wallet['Shares']:
			shares[share['ContractId']] = share['Quantity']

		#get current bitcoin volatility
		volJson = requests.get('https://btcvol.info/latest', data={}, headers={}).json()
		vol = volJson['Volatility']

		#get current bitfinex price
		#bitfinexJson = requests.get('https://api.bitfinex.com/v1/pubticker/BTCUSD', data={}, headers={}).json()
		#price = float(bitfinexJson['last_price'])
		#get bitfinex 24 hour spread between high and low to calculate uncertainty
		#high = float(bitfinexJson['high'])
		#low = float(bitfinexJson['low'])

		#get current bitstamp price
		bitstampJson = requests.get('https://www.bitstamp.net/api/ticker/', data={}, headers={}).json()
		price = float(bitstampJson['last'])
		#get bitstamp 24 hour spread between high and low to calculate uncertainty
		high = float(bitstampJson['high'])
		low = float(bitstampJson['low'])

		print('Price: ' + str(price))
		print('24hr High: ' + str(high))
		print('24hr Low: ' + str(low))
		uncertaintyFactor = high / low
		uncertaintyFactor = uncertaintyFactor ** 1.5
		vol = vol / 1.04 * uncertaintyFactor * customShortVol
		print('Volatility: ' + str(vol))
		uncertaintyFactor = uncertaintyFactor * customUncertainty
		downMomentum = (high / price) ** 1.5
		upMomentum = (price / low) ** 1.5

		print('UncertaintyFactor: ' + str(uncertaintyFactor))

		now = datetime.now()

		#calculate estimated percentages on contracts
		for priceContract in priceContracts:
			contractShares = 0
			if priceContract.id in shares:
				contractShares = shares[priceContract.id]
		
			timeDelta = priceContract.endDate - now
			days = timeDelta.days + timeDelta.seconds/60.0/60.0/24.0
			days = days + gmtOffset/24 #adjust for time zone
			if days < 0.25 or days > 365:
				continue
			#adjusting to expect bigger jumps in short time span
			days = days + daysAdded
			shortVol = vol * .9975 + customShortVol - 1
			adjVol = ((shortVol * (365-days) + baseVol*(days))/365*4 + baseVol) / 5.0
			
			predictedPrice = price * (1+dailyPercentReturn/100) ** days
			stdev = adjVol / 100 * predictedPrice
			stdevSample = stdev * math.sqrt(days)
			contractPrice = priceContract.price
			odds = calcodds(predictedPrice, contractPrice, days, adjVol)
			
			#turn odds into EV
			odds = (odds * 3 + (odds*contractPrice)/(odds*contractPrice + (1-odds)*predictedPrice))/4
			
			print("Estimated odds of occurring: " + str(odds * 100) + '%')
			if contractShares != 0:
				sharesModifier = (math.pow(abs(contractShares), 0.6) / 100) * (0.5 - abs(odds - 0.5)) * 1.33
				if contractShares > 0:
					odds -= sharesModifier
				else:
					odds += sharesModifier
				print(str(contractShares) + " shares held, adjusted odds: " + str(odds * 100) + '%')
			orderPrice = int(1000*odds)
			
			#increase uncertainty in days approaching deadline
			adjUncertaintyFactor = uncertaintyFactor
			if days < 5:
				adjUncertaintyFactor = uncertaintyFactor * (1.5 - days / 10)
			elif days > 30:
				adjUncertaintyFactor = uncertaintyFactor *  math.sqrt(1+(days-30)/730)
			
			#fixedBest = 24
			fixedBest = 30
			fixedGood = 19
			fixedOk = 15
			bestSpread = ((500 - abs(500 - 1000 * odds)) * 0.31) * adjUncertaintyFactor
			goodSpread = ((500 - abs(500 - 1000 * odds)) * 0.24) * adjUncertaintyFactor
			okSpread = ((500 - abs(500 - 1000 * odds)) * 0.18) * adjUncertaintyFactor
			bestBuyPrice = int((orderPrice - fixedBest - bestSpread * downMomentum * (2 - bullishness))) * 1000
			goodBuyPrice = int((orderPrice - fixedGood - goodSpread * downMomentum * (2 - bullishness))) * 1000
			okBuyPrice = int((orderPrice - fixedOk - okSpread * downMomentum * (2 - bullishness))) * 1000
			bestSellPrice = int((orderPrice + fixedBest + bestSpread * upMomentum * bullishness)) * 1000
			goodSellPrice = int((orderPrice + fixedGood + goodSpread * upMomentum * bullishness)) * 1000
			okSellPrice = int((orderPrice + fixedOk + okSpread * upMomentum * bullishness)) * 1000
			#print('Best spread: ' + str(bestSpread) + ', Good spread: ' + str(goodSpread) + ', OK spread: ' + str(okSpread))
			
			bestBuyPrice = optimizeOrderPrice(bestBuyPrice, False, True)
			bestSellPrice = optimizeOrderPrice(bestSellPrice, True, True)
			#print(str(days) + ', ' + str(contractPrice) + ', ' + str(bestBuyPrice) + ', ' + str(goodBuyPrice) + ', ' + str(okBuyPrice) + ', ' + str(okSellPrice) + ', ' + str(goodSellPrice) + ', ' + str(bestSellPrice))
			
			#get open orders for this contract
			openOrders = requests.get(predictiousUrl + '/contractorders/' + priceContract.id, data={}, headers=headers).json()
			
			ordersToAdd = []
			
			for ask in openOrders['Asks']:
				if bestBuyPrice >= ask['Price']:
					#we're immediately filling this order
					quantity = ask['Quantity']
					if quantity > bestShares:
						quantity = bestShares
					orderPrice = ask['Price']
					ordersToAdd.append({'ContractId' : priceContract.id, 'IsAsk' : 'false', 'Quantity' : quantity, 'Price' : orderPrice, 'ExpirationSeconds' : 7200})
					print('Buying ' + str(quantity) + ' of "'+ priceContract.name + '" for ' + str(orderPrice/10000) + '%')
			
			doLimitOrder = False
			orderPrice = 0
			quantity = 0
			
			if bestBuyPrice >= 2000:
				quantity = optimizeQuantity(bestShares, bestBuyPrice, False)
				ordersToAdd.append({'ContractId' : priceContract.id, 'IsAsk' : 'false', 'Quantity' : quantity, 'Price' : bestBuyPrice, 'ExpirationSeconds' : 7200})
				print('Bidding ' + str(quantity) + ' of "' + priceContract.name + '" for ' + str(bestBuyPrice/10000) + '%')
			
			if openOrders['Bids']:
				bestBid = openOrders['Bids'][0]
				if bestBuyPrice > bestBid['Price']:
					doLimitOrder = False #do nothing, we already have the best order
				elif goodBuyPrice >= bestBid['Price'] and goodBuyPrice >= 2000:
					orderPrice = bestBid['Price'] + 1000
					quantity = goodShares
					doLimitOrder = True
				elif okBuyPrice >= bestBid['Price']:
					orderPrice = bestBid['Price'] + 1000
					quantity = okShares
					doLimitOrder = True
			
			if doLimitOrder and orderPrice >= 2000:
				orderPrice = optimizeOrderPrice(orderPrice, False, False)
				quantity = optimizeQuantity(quantity, orderPrice, False)
				ordersToAdd.append({'ContractId' : priceContract.id, 'IsAsk' : 'false', 'Quantity' : quantity, 'Price' : orderPrice, 'ExpirationSeconds' : 7200})
				print('Bidding ' + str(quantity) + ' of "' + priceContract.name + '" for ' + str(orderPrice/10000) + '%')
				
			for bid in openOrders['Bids']:
				if bestSellPrice <= bid['Price']:
					#we're immediately filling this order
					quantity = bid['Quantity']
					if quantity > bestShares:
						quantity = bestShares
					orderPrice = bid['Price']
					ordersToAdd.append({'ContractId' : priceContract.id, 'IsAsk' : 'true', 'Quantity' : quantity, 'Price' : orderPrice, 'Prediction' : odds, 'ExpirationSeconds' : 7200})
					print('Selling ' + str(quantity) + ' of "'+ priceContract.name + '" for ' + str(orderPrice/10000) + '%')
			
			if bestSellPrice <= 998000:
				quantity = optimizeQuantity(bestShares, bestSellPrice, True)
				ordersToAdd.append({'ContractId' : priceContract.id, 'IsAsk' : 'true', 'Quantity' : quantity, 'Price' : bestSellPrice, 'ExpirationSeconds' : 7200})
				print('Asking ' + str(quantity) + ' of "' + priceContract.name + '" for ' + str(bestSellPrice/10000) + '%')
			
			doLimitOrder = False
			orderPrice = 0
			quantity = 0
			if openOrders['Asks']:
				bestAsk = openOrders['Asks'][0]
				if bestSellPrice < bestAsk['Price']:
					doLimitOrder = False #do nothing, we already have the best order
				elif goodSellPrice <= bestAsk['Price'] and goodSellPrice <= 998000:
					orderPrice = bestAsk['Price'] - 1000
					quantity = goodShares
					doLimitOrder = True
				elif goodSellPrice <= bestAsk['Price']:
					orderPrice = bestAsk['Price'] - 1000
					quantity = okShares
					doLimitOrder = True
			if doLimitOrder and orderPrice <= 998000:
				orderPrice = optimizeOrderPrice(orderPrice, True, False)
				quantity = optimizeQuantity(quantity, orderPrice, True)
				ordersToAdd.append({'ContractId' : priceContract.id, 'IsAsk' : 'true', 'Quantity' : quantity, 'Price' : orderPrice, 'ExpirationSeconds' : 7200})
				print('Asking ' + str(quantity) + ' of "' + priceContract.name + '" for ' + str(orderPrice/10000) + '%')

			if ordersToAdd:
				do_call('addorders', ordersToAdd)
	except Exception as e:
		print(e)
		pass
	print('Sleeping 30 minutes...')
	time.sleep(1800)
